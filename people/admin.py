from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Person, User


class PersonInline(admin.StackedInline):
    model = Person
    can_delete = False
    fk_name = "user"
    fields = ["full_name", "designation", "department", "employee_id", "phone", "office", "avatar"]


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ["email"]
    list_display = ["email", "first_name", "last_name", "is_active", "is_superuser", "last_login"]
    list_filter = ["is_active", "is_superuser", "person__department"]
    search_fields = ["email", "first_name", "last_name", "person__full_name"]
    inlines = [PersonInline]
    fieldsets = (
        (None, {"fields": ("email", "username", "password")}),
        ("Name", {"fields": ("first_name", "last_name")}),
        ("Access", {"fields": ("is_active", "is_staff", "is_superuser", "must_change_password")}),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),)
    filter_horizontal = ()


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ["full_name", "designation", "department", "user"]
    list_filter = ["department"]
    search_fields = ["full_name", "user__email", "employee_id"]
