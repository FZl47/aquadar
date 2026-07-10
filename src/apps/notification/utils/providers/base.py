import abc

from django_q.tasks import async_task

from apps.notification.models import NotificationUser


class BaseProvider(abc.ABC):
    """
    Base class for all notification providers.

    This class acts as an interface that all notification providers
    (such as SMS, Email, Firebase, etc.) must inherit from and
    implement the `send` method.

    Each provider is responsible for delivering notifications
    through a specific communication channel.

    The public `send` method always runs as a django-q background task.
    Subclasses must implement `_send` only.
    """

    def __init__(self,notification: NotificationUser) -> None:
        self.notification = notification


    def send(self) -> None:
        """
        Public method used to send a notification.

        This method queues the actual sending logic on django-q.
        Subclasses MUST NOT override this method.
        """
        provider_path = f'{type(self).__module__}.{type(self).__qualname__}'
        async_task(
            'apps.notification.utils.providers.base._run_provider_send',
            provider_path,
            self.notification.pk,
        )

    @abc.abstractmethod
    def _send(self, notification: NotificationUser) -> None:
        """
        Internal method containing the actual sending logic.

        This method must be implemented by subclasses.
        """
        raise NotImplementedError

    def _send_wrapper(self, notification: NotificationUser) -> None:
        """
        Wrapper around `_send` to handle cross-cutting concerns
        such as error handling, logging, retries, etc.
        """
        try:
            self._send(notification)
        except Exception as exc:
            self._handle_error(exc, notification)

    def _handle_error(self, exc: Exception, notification: NotificationUser) -> None:
        """
        Handle exceptions raised during notification sending.
        Can be overridden if needed.
        """
        pass


def _run_provider_send(provider_class_path: str, notification_id: int) -> None:
    """django-q entry point: re-fetch the notification and dispatch `_send`."""
    from django.utils.module_loading import import_string

    try:
        notification = NotificationUser.objects.get(pk=notification_id)
    except NotificationUser.DoesNotExist:
        return

    provider_class = import_string(provider_class_path)
    provider = provider_class(notification)
    provider._send_wrapper(notification)
