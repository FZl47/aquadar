import inspect
from typing import Any, Callable, Optional, Union, Iterable

from django.contrib.auth import get_user_model
from django.db.models import QuerySet
from django.db import models
from django.utils.functional import SimpleLazyObject

from apps.notification import utils

ValueOrCallable = Union[Any, Callable]

User = SimpleLazyObject(get_user_model)


class NotificationModelMixin:
    """
    Abstract mixin that automatically creates a notification when
    a model instance is created or updated.

    Notification configuration attributes may be defined as:
        - Static values
        - Callables accepting the model instance and returning a value

    The notification is created inside the `save()` method only
    when the object is created or updated.

    Configurable attributes (override in subclasses):

        _notif_create_only_first:
           bool

        _notif_title:
            str | Callable[[Model], str]

        _notif_to_users:
            User | Callable[[Model], User]

        _notif_type:
            str | Callable[[Model], str]

        _notif_image:
            str | None | Callable[[Model], str | None]

        _notif_kwargs:
            dict | Callable[[Model], dict]

        _notif_description:
            str | Callable[[Model], str]

        _notif_send_notify:
            bool | Callable[[Model], bool]
    """

    _notif_create_only_first: bool = True
    _notif_title: ValueOrCallable = None
    # _notif_to_users: ValueOrCallable = None
    _notif_type: ValueOrCallable = None
    _notif_image: Optional[ValueOrCallable] = None
    _notif_kwargs: Optional[ValueOrCallable] = None
    _notif_description: Optional[ValueOrCallable] = None
    _notif_send_notify: ValueOrCallable = True

    def _f_notif_title(self) -> Any:
        return self._resolve_notif_value("title")

    def _f_notif_to_users(self) -> Any:
        return self._resolve_notif_value("to_users")

    def _f_notif_type(self) -> Any:
        return self._resolve_notif_value("type")

    def _f_notif_image(self) -> Any:
        return self._resolve_notif_value("image")

    def _f_notif_kwargs(self) -> dict:
        return self._resolve_notif_value("kwargs", {})

    def _f_notif_description(self) -> Any:
        return self._resolve_notif_value("description")

    def _f_notif_send_notify(self) -> bool:
        return self._resolve_notif_value("send_notify", True)

    def _f_notif_create_only_first(self) -> bool:
        return self._resolve_notif_value("create_only_first", True)

    def _resolve_notif_value(self, name: str, default: Any = None) -> Any:
        """
        Resolves a notification configuration by name.

        Priority:
            1. get_notif_<name>() method (if exists)
            2. _notif_<name> attribute (if exists)
            3. default

        If the resolved value is callable, it will be called with `self`.
        """
        #  Check for method override
        value = getattr(self, f'get_notif_{name}', None)
        if not callable(value):
            #  Fallback to attribute
            value = getattr(self, f'_notif_{name}', None)

        # If callable, call it with self
        if callable(value) and not isinstance(value, type):
            return value()
        if value is None:
            return default
        return value

    def save(self, *args, **kwargs):

        self.is_created = self.pk is None

        super().save(*args, **kwargs)
        if self._f_notif_create_only_first():
            if self.is_created:
                self._create_notification()
        else:
            self._create_notification()

    def _create_notification(self) -> None:
        """
            Creates a notification based on resolved configuration values.
        """

        to_users = self._f_notif_to_users()
        if not to_users:
            return None  # No target user

        payload = {
            "title": self._f_notif_title(),
            "type_notif": self._f_notif_type(),
            "image": self._f_notif_image(),
            "description": self._f_notif_description(),
            "kwargs_notif": self._f_notif_kwargs(),
            "send_notify": self._f_notif_send_notify(),
        }

        for user in to_users:
            payload['to_user'] = user
            utils.create_user_notif(**payload)

        return None

    @staticmethod
    def all_users() -> QuerySet[User]:
        """
        Returns all active users.
        """
        return User.objects.filter(is_active=True)

    @staticmethod
    def admin_users() -> QuerySet[User]:
        """
        Returns admin users.
        """
        return User.objects.filter(is_active=True, is_superuser=True)

    @staticmethod
    def user_perms(permissions: Iterable[str]) -> QuerySet[User]:
        return (
            User.objects.filter(is_active=True).filter(
                models.Q(user_permissions__codename__in=permissions) | models.Q(
                    groups__permissions__codename__in=permissions)
            ).distinct()
        )
