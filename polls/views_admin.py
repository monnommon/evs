from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework import generics, permissions, status, views
from rest_framework.response import Response

from accounts.models import Role
from accounts.serializers import ChangeUserRoleSerializer, RoleSerializer, UserSerializer
from audit.utils import audit_trail, log_event, verify_chain
from polls.models import AnonymousSession, Poll, PollStatus, Vote
from polls.serializers import (
    AnonymousSessionSerializer,
    PollCreateSerializer,
    PollResultsSerializer,
    PollSerializer,
    PollUpdateSerializer,
)


class IsAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.has_permission("create_poll"))


class AdminOrResultsViewer(permissions.BasePermission):
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        return request.user.has_permission("view_results") or request.user.has_permission("create_poll")


# ---------------- Admin panel API (/api/admin/...) ----------------


class AdminPollListView(generics.ListCreateAPIView):
    permission_classes = [IsAdmin]

    def get_serializer_class(self):
        return PollCreateSerializer if self.request.method == "POST" else PollSerializer

    def get_queryset(self):
        return Poll.objects.all().prefetch_related("options")

    def perform_create(self, serializer):
        poll = serializer.save(created_by=self.request.user)
        log_event("poll_created", "Poll", str(poll.id), {"title": poll.title, "is_anonymous": poll.is_anonymous}, created_by=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(PollSerializer(serializer.instance, context=self.get_serializer_context()).data, status=status.HTTP_201_CREATED)


class AdminPollDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAdmin]
    serializer_class = PollSerializer

    def get_queryset(self):
        return Poll.objects.all().prefetch_related("options")

    def update(self, request, *args, **kwargs):
        poll = self.get_object()
        if poll.is_finalized:
            return Response({"detail": "Poll is finalized and immutable."}, status=status.HTTP_409_CONFLICT)
        mutable_fields = {"title", "description", "start_at", "end_at", "is_anonymous", "allow_multiple_options", "status"}
        data = {k: v for k, v in request.data.items() if k in mutable_fields}
        serializer = PollUpdateSerializer(poll, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        old_status = poll.status
        serializer.save()
        log_event("poll_updated", "Poll", str(poll.id), {"fields": sorted(data.keys())}, created_by=request.user)
        if "status" in data and data["status"] != old_status:
            log_event("poll_status_changed", "Poll", str(poll.id), {"from": old_status, "to": data["status"]}, created_by=request.user)
        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        poll = self.get_object()
        if poll.is_finalized or poll.votes.exists():
            return Response({"detail": "Poll with votes or finalized results cannot be deleted."}, status=status.HTTP_409_CONFLICT)
        log_event("poll_updated", "Poll", str(poll.id), {"deleted": True, "title": poll.title}, created_by=request.user)
        poll.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminPollResultsView(generics.RetrieveAPIView):
    permission_classes = [AdminOrResultsViewer]

    def get(self, request, *args, **kwargs):
        poll = generics.get_object_or_404(Poll, pk=kwargs["pk"])
        data = PollResultsSerializer.build(poll, request=request)
        return Response(data)


class AdminFinalizePollView(views.APIView):
    permission_classes = [IsAdmin]

    def post(self, request, pk):
        with transaction.atomic():
            poll = generics.get_object_or_404(Poll.objects.select_for_update(), pk=pk)
            if poll.is_finalized:
                return Response({"detail": "Poll already finalized."}, status=status.HTTP_409_CONFLICT)
            poll.status = PollStatus.CLOSED
            poll.finalized_at = timezone.now()
            poll.save(update_fields=["status", "finalized_at"])
            tally = PollResultsSerializer.build(poll)["tally"]
            log_event(
                "result_finalized",
                "Poll",
                str(poll.id),
                {"status": "closed", "tally": tally, "finalized_at": poll.finalized_at.isoformat()},
                created_by=request.user,
            )
        return Response(PollSerializer(poll).data)


class AdminUserListView(generics.ListAPIView):
    permission_classes = [IsAdmin]
    serializer_class = UserSerializer

    def get_queryset(self):
        User = get_user_model()
        qs = User.objects.select_related("role").all()
        return qs.order_by("email")


class AdminChangeUserRoleView(views.APIView):
    permission_classes = [IsAdmin]

    def post(self, request, pk):
        User = get_user_model()
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = ChangeUserRoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            role = Role.objects.get(pk=serializer.validated_data["role_id"])
        except Role.DoesNotExist:
            return Response({"detail": "Role not found."}, status=status.HTTP_404_NOT_FOUND)
        old_role = user.role.name if user.role else None
        user.role = role
        user.save(update_fields=["role"])
        log_event("role_changed", "User", str(user.id), {"from": old_role, "to": role.name}, created_by=request.user)
        return Response(UserSerializer(user).data)


class AdminRoleListView(generics.ListAPIView):
    permission_classes = [IsAdmin]
    serializer_class = RoleSerializer
    queryset = Role.objects.all()


class AdminGenerateLinkView(views.APIView):
    permission_classes = [IsAdmin]

    def post(self, request, pk):
        poll = generics.get_object_or_404(Poll, pk=pk)
        if not poll.is_anonymous:
            return Response({"detail": "Links can only be generated for anonymous polls."}, status=status.HTTP_400_BAD_REQUEST)
        if poll.is_finalized or not poll.is_open:
            return Response({"detail": "Links can only be generated while the poll is open."}, status=status.HTTP_409_CONFLICT)
        session = AnonymousSession.objects.create_session(poll, ttl_hours=request.data.get("ttl_hours"))
        log_event("session_generated", "Poll", str(poll.id), {"session_id": str(session.id), "expires_at": session.expires_at.isoformat()}, created_by=request.user)
        return Response(AnonymousSessionSerializer(session, context={"request": request}).data, status=status.HTTP_201_CREATED)


class AdminAuditVerifyView(views.APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        ok, problems = verify_chain()
        from audit.models import AuditLog

        return Response({"chain_valid": ok, "problems": problems, "entries": AuditLog.objects.count()})
