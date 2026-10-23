from django.contrib.auth.models import Permission

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _

from . import models

admin.site.register(Permission)


@admin.register(models.UserLoginActivity)
class UserLoginActivityAdmin(admin.ModelAdmin):
    list_display = ('user', 'ip', 'created_at')
    search_fields = ('user__username', 'ip')
    date_hierarchy = 'created_at'


@admin.register(models.User)
class UserAdmin(BaseUserAdmin):
    model = models.User

    list_display = (
        'id',
        'username',
        'first_name',
        'last_name',
        'role',
        'is_active',
        'is_staff',
        'is_superuser',
        'farm_names',
        'profile_is_completed',
        'created_at',
    )

    list_filter = (
        'role',
        'farms',
        'is_active',
        'is_staff',
        'is_superuser',
    )

    search_fields = (
        'username',
        'first_name',
        'last_name',
        'phonenumber',
    )

    ordering = ('-created_at',)

    fieldsets = (
        (None, {
            'fields': (
                'password',
            )
        }),
        (_('Personal info'), {
            'fields': (

                'first_name',
                'last_name',
                'phonenumber',
                'rubika_id',
            )
        }),
        (_('Farms'), {
            'fields': (
                'farms',
            )
        }),
        (_('Role & Permissions'), {
            'fields': (
                'username',
                'role',
                'is_active',
                'is_staff',
                'is_superuser',
                'groups',
                'user_permissions',
            )
        }),
        (_('Important dates'), {
            'fields': (
                'last_login',
                'created_at',
                'updated_at',
            )
        }),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': (
                'username',
                'password1',
                'password2',
                'farms',
                'role',
                'is_active',
                'is_staff',
            ),
        }),
    )

    readonly_fields = (
        'last_login',
        'created_at',
        'updated_at',
    )

    filter_horizontal = (
        'farms',
        'groups',
        'user_permissions',
    )

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('farms')

    @admin.display(description=_('Farms'))
    def farm_names(self, obj):
        return ', '.join(farm.name for farm in obj.farms.all())


@admin.register(models.UserHostRestrict)
class UserHostRestrictAdmin(admin.ModelAdmin):
    list_display = ('host',)
    filter_horizontal = ('users',)