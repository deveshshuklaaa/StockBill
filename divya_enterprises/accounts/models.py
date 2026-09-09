from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    ROLE_ADMIN = "admin"
    ROLE_STAFF = "staff"
    ROLE_CHOICES = [
        (ROLE_ADMIN, "Admin"),
        (ROLE_STAFF, "Staff"),
    ]

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_STAFF)

    @property
    def normalized_role(self):
        return str(self.role or "").strip().lower()

    def __str__(self):
        return f"{self.username} ({self.role})"
