from django.contrib import admin

from .models import AnonymousSession, Option, Poll, Vote


class OptionInline(admin.TabularInline):
    model = Option
    extra = 0


@admin.register(Poll)
class PollAdmin(admin.ModelAdmin):
    list_display = ["title", "status", "is_anonymous", "start_at", "end_at", "finalized_at", "created_by"]
    list_filter = ["status", "is_anonymous"]
    search_fields = ["title"]
    inlines = [OptionInline]


@admin.register(Vote)
class VoteAdmin(admin.ModelAdmin):
    list_display = ["poll", "user", "voted_at", "is_valid", "fingerprint_hash"]
    list_filter = ["poll", "is_valid"]
    readonly_fields = [f.name for f in Vote._meta.fields]


@admin.register(AnonymousSession)
class AnonymousSessionAdmin(admin.ModelAdmin):
    list_display = ["poll", "token", "created_at", "expires_at", "used", "is_expired"]
    readonly_fields = ["token", "created_at"]