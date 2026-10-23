from django.utils.translation import gettext_lazy as _
from django.contrib.auth.models import AbstractUser, PermissionsMixin
from django.contrib.auth.base_user import BaseUserManager
from django.db import models

from apps.core.models import BaseModel
from apps.core.utils.validators import PhonenumberValidator
from apps.notification.models import NotificationUser as NotifUser
from apps.public.models import Farm


class CustomUserManager(BaseUserManager):

    def get_queryset(self):
        return super().get_queryset().filter(is_active=True)

    def get_available_users(self):
        # Get users (exclude superusers)
        return self.get_queryset().filter(is_superuser=False)

    def create_user(self, username, password=None, **extra_fields):
        if not username:
            raise ValueError(_('The Email field must be set'))
        farms = extra_fields.pop('farms', None)

        user = self.model(username=username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)

        if farms:
            user.farms.set(farms)

        return user

    def create_superuser(self, username, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('role', 'waterman')
        extra_fields.setdefault('farms', Farm.objects.all())

        if not extra_fields.get('is_staff'):
            raise ValueError(_('Superuser must have is_staff=True.'))
        if not extra_fields.get('is_superuser'):
            raise ValueError(_('Superuser must have is_superuser=True.'))

        return self.create_user(username, password, **extra_fields)


class User(BaseModel, AbstractUser, PermissionsMixin):
    ROLE_TYPES = (
        ('supervisor', _('Supervisor User')),
        ('waterman', _('Waterman User')),
    )

    first_name = models.CharField(_("first name"), max_length=150, blank=True, default=_('No name'))
    last_name = models.CharField(_("last name"), max_length=150, blank=True, default='')
    phonenumber = models.CharField(_("Phonenumber"), null=True, blank=True, max_length=20,
                                   validators=[PhonenumberValidator()])
    rubika_id = models.CharField(_("Rubika ID"), null=True, blank=True, max_length=64)

    role = models.CharField(max_length=15, choices=ROLE_TYPES, default='waterman', verbose_name=_('Role'))
    farms = models.ManyToManyField('public.Farm', verbose_name=_('Farms'))

    class Meta(AbstractUser.Meta):
        verbose_name = _('User')
        verbose_name_plural = _('Users')

    objects = CustomUserManager()
    all_objects = models.Manager()

    REQUIRED_FIELDS = []

    @property
    def profile_is_completed(self):
        if self.is_superuser:
            return True

        if self.first_name and self.last_name and self.username and self.phonenumber:
            return True
        return False

    @property
    def has_run_active(self):
        return self.run_set.filter(status='open').exists()

    def create_notif(self, notif_kw=None, **kwargs):
        if 'user' in kwargs and 'to_user' not in kwargs:
            kwargs['to_user'] = kwargs.pop('user')
        kwargs.setdefault('to_user', self)
        return NotifUser.objects.create(**kwargs, kwargs=notif_kw)


class UserLoginActivity(BaseModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name=_('User'))
    ip = models.CharField(max_length=24, verbose_name=_('IP Address'))
    agent = models.TextField(null=True, verbose_name=_('User Agent'))

    class Meta:
        verbose_name = _('Login Activity')
        verbose_name_plural = _('Login Activities')

    def __str__(self):
        return f'{self.user} | {self.ip}'


class UserHostRestrict(BaseModel):
    host = models.CharField(max_length=128, verbose_name=_('Host'))
    users = models.ManyToManyField('account.User', verbose_name=_('Users'))

    class Meta:
        verbose_name = _('Host Restriction')
        verbose_name_plural = _('Host Restrictions')
