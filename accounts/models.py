import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class Role(models.Model):
    """Named role with a JSONB permission list (Admin, Secretariat, User)."""

    class Roles(models.TextChoices):
        ADMIN = "Admin"
        SECRETARIAT = "Secretariat"
        USER = "User"

    DEFAULT_PERMISSIONS = {
        Roles.ADMIN: ["create_poll", "view_results", "vote", "manage_users", "finalize_poll", "generate_links"],
        Roles.SECRETARIAT: ["view_results"],
        Roles.USER: ["vote"],
    }

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=50, unique=True)
    permissions = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @classmethod
    def ensure_defaults(cls):
        """Idempotently create the three canonical roles."""
        for role_name, perms in cls.DEFAULT_PERMISSIONS.items():
            cls.objects.get_or_create(name=role_name, defaults={"permissions": perms})

    def has_permission(self, permission):
        return permission in (self.permissions or [])


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        from django.contrib.auth.models import Permission

        role = Role.objects.filter(name=Role.Roles.ADMIN).first()
        if role is None:
            Role.ensure_defaults()
            role = Role.objects.get(name=Role.Roles.ADMIN)
        user = self.create_user(email, password, role=role, **extra_fields)
        user.is_superuser = True
        user.is_staff = True
        user.save(using=self._db)
        return user


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True, db_index=True)
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="users", null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_login = models.DateTimeField(null=True, blank=True)
    # spec field: password_hash — Django stores this in `password` (PBKDF2/Argon2).
    # Kept as a property for schema parity; the real column is `password`.

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        ordering = ["email"]

    def __str__(self):
        return self.email

    @property
    def password_hash(self):
        return self.password

    def get_full_name(self):
        return self.email

    def get_short_name(self):
        return self.email

    def has_permission(self, permission):
        return self.is_superuser or (self.role is not None and self.role.has_permission(permission))