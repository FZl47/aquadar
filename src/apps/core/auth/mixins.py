from abc import ABC

from typing import Union, Sequence

from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.conf import settings


class PermissionMixin(ABC):
    """
        An interface to manage user permission to take action
    """

    permissions: Union[None, Sequence] = None
    raise_exc: bool = True

    def __init_subclass__(cls, **kwargs):
        """
            Check subclass inherit
        """

        assert cls.permissions is not None, 'You must define field `permissions` in `%s` class' % cls.__name__

    def _perm_check(self, request):
        """
            Check user authentication and authoritarian state
            :param request:
            :return bool:
        """
        user = request.user

        if not user.is_authenticated:
            return False

        return user.has_perms(self.permissions)

    def dispatch(self, request, *args, **kwargs):

        has_perm = self._perm_check(request)
        if not has_perm:
            if self.raise_exc:
                raise PermissionDenied
            return redirect(settings.LOGIN_URL)

        return super().dispatch(request, *args, **kwargs)


class UserAuthenticatedRequiredMixin(ABC):
    """
        An interface to manage user is authenticated to take action
    """

    raise_exc: bool = True

    def _perm_check(self, request):
        """
            Check user authentication and authoritarian state
            :param request:
            :return bool:
        """
        user = request.user

        if not user.is_authenticated:
            return False

        return True

    def dispatch(self, request, *args, **kwargs):

        has_perm = self._perm_check(request)
        if not has_perm:
            if self.raise_exc:
                raise PermissionDenied
            return redirect(settings.LOGIN_URL)

        return super().dispatch(request, *args, **kwargs)


class SuperVisorUserRequiredMixin(ABC):
    """
        An interface to manage supervisor users to take action
    """

    raise_exc: bool = True

    def _perm_check(self, request):
        user = request.user

        if not user.is_authenticated:
            return False

        if user.is_superuser:
            return True

        if not user.role == 'supervisor':
            return False

        return True

    def dispatch(self, request, *args, **kwargs):

        has_perm = self._perm_check(request)
        if not has_perm:
            if self.raise_exc:
                raise PermissionDenied
            return redirect(settings.LOGIN_URL)

        return super().dispatch(request, *args, **kwargs)


class WatermanUserRequiredMixin(ABC):
    """
        An interface to manage waterman users to take action
    """

    raise_exc: bool = True

    def _perm_check(self, request):
        user = request.user

        if not user.is_authenticated:
            return False

        if user.is_superuser:
            return True

        if not user.role == 'waterman':
            return False

        return True

    def dispatch(self, request, *args, **kwargs):

        has_perm = self._perm_check(request)
        if not has_perm:
            if self.raise_exc:
                raise PermissionDenied
            return redirect(settings.LOGIN_URL)

        return super().dispatch(request, *args, **kwargs)
