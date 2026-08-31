from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Role, User


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ["name", "permissions"]
    search_fields = ["name"]


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ["email"]
    list_display = ["email", "role", "is_active", "created_at", "last_login"]
    search_fields = ["email"]
    list_filter = ["is_active", "role"]
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Role", {"fields": ("role",)}),
        ("Flags", {"fields": ("is_active", "is_staff", "is_superuser")}),
        ("Dates", {"fields": ("last_login", "created_at")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "password1", "password2", "role")}),)
    readonly_fields = ["created_at"]
    filter_horizontal = []