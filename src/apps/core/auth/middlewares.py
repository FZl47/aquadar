from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.conf import settings

from apps.account.models import UserHostRestrict as UserHostRestrictModel


class UserIsAuthenticated:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = str(request.path)
        if request.user.is_anonymous:
            if not any([str(url) in path for url in settings.EXCEPT_USER_AUTH_URLS]):
                return redirect(settings.LOGIN_URL)
        response = self.get_response(request)
        return response


class UserProfileIsCompleted:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = str(request.path)

        if not request.user.is_anonymous and not request.user.profile_is_completed:
            if not any([str(url) in path for url in settings.EXCEPT_USER_PROFILE_URLS]):
                return redirect(settings.PROFILE_URL)
        response = self.get_response(request)

        return response


class UserHostRestrict:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host()
        host_restrict = None
        user = request.user

        if not user.is_anonymous:
            # TODO: should use cache system for optimize
            host_restrict = UserHostRestrictModel.objects.filter(host=host, users__in=[user])
        if host_restrict:
            raise PermissionDenied
        response = self.get_response(request)

        return response
