from django.db.models import Count, Q
from rest_framework import serializers

from audit.utils import audit_trail
from .models import AnonymousSession, Option, Poll, Vote


class OptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Option
        fields = ["id", "text", "order"]


class OptionCreateSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=500)
    order = serializers.IntegerField(required=False, default=0)


class PollSerializer(serializers.ModelSerializer):
    options = OptionSerializer(many=True, read_only=True)
    created_by_email = serializers.CharField(source="created_by.email", read_only=True)
    is_open = serializers.BooleanField(read_only=True)

    class Meta:
        model = Poll
        fields = [
            "id",
            "title",
            "description",
            "created_by",
            "created_by_email",
            "is_anonymous",
            "allow_multiple_options",
            "start_at",
            "end_at",
            "status",
            "finalized_at",
            "created_at",
            "options",
            "is_open",
        ]
        read_only_fields = ["id", "created_by", "created_by_email", "status", "finalized_at", "created_at"]


class PollCreateSerializer(serializers.ModelSerializer):
    options = OptionCreateSerializer(many=True, write_only=True, required=True)

    class Meta:
        model = Poll
        fields = ["title", "description", "is_anonymous", "allow_multiple_options", "start_at", "end_at", "options"]

    def create(self, validated_data):
        options_data = validated_data.pop("options")
        poll = Poll.objects.create(**validated_data)
        for option_data in options_data:
            poll.options.create(text=option_data["text"], order=option_data.get("order", 0))
        return poll

    def validate_options(self, value):
        if len(value) < 2:
            raise serializers.ValidationError("A poll needs at least two options.")
        seen_orders = [o.get("order", 0) for o in value]
        if len(set(seen_orders)) != len(seen_orders):
            raise serializers.ValidationError("Option orders must be unique.")
        return value

    def validate(self, data):
        if data.get("end_at") and data.get("start_at") and data["end_at"] <= data["start_at"]:
            raise serializers.ValidationError("end_at must be after start_at.")
        return data


class VoteSerializer(serializers.Serializer):
    option_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=False)

    def validate(self, data):
        poll = self.context["poll"]
        option_ids = data["option_ids"]
        if len(set(option_ids)) != len(option_ids):
            raise serializers.ValidationError("Duplicate option ids are not allowed.")
        valid_ids = set(poll.options.values_list("id", flat=True))
        unknown = set(option_ids) - valid_ids
        if unknown:
            raise serializers.ValidationError(f"Options do not belong to this poll: {sorted(str(u) for u in unknown)}")
        if not poll.allow_multiple_options and len(option_ids) > 1:
            raise serializers.ValidationError("This poll allows only one option.")
        return data


class VoteResultSerializer(serializers.ModelSerializer):
    options = OptionSerializer(many=True, read_only=True)

    class Meta:
        model = Vote
        fields = ["id", "poll", "user", "options", "voted_at", "is_valid"]


class AnonymousSessionSerializer(serializers.ModelSerializer):
    vote_url = serializers.SerializerMethodField()

    class Meta:
        model = AnonymousSession
        fields = ["id", "poll", "token", "created_at", "expires_at", "used", "vote_url"]
        read_only_fields = ["id", "token", "created_at", "used"]

    def get_vote_url(self, obj):
        request = self.context.get("request")
        base = request.build_absolute_uri("/") if request else ""
        return f"{base.rstrip('/')}/poll/{obj.token}"


class PollResultsSerializer(serializers.Serializer):
    """Tally + audit trail (exportable for external verification)."""

    @staticmethod
    def build(poll, request=None):
        tally = list(poll.options.annotate(n=Count("votes", filter=Q(votes__is_valid=True))).values("id", "text", "order", "n"))
        total_votes = poll.votes.filter(is_valid=True).count()
        return {
            "poll": PollSerializer(poll, context={"request": request}).data,
            "total_valid_votes": total_votes,
            "tally": tally,
            "finalized": poll.is_finalized,
            "audit_trail": audit_trail(entity_type="Poll", entity_id=poll.id),
        }