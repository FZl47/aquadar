import abc
import logging

from django.db import transaction

from apps.notification.models import NotificationUser
from apps.notification.tasks import send_notification_via_provider

logger = logging.getLogger(__name__)


class BaseProvider(abc.ABC):
    """
    Base class for all notification providers.

    This class acts as an interface that all notification providers
    (such as SMS, Email, Firebase, etc.) must inherit from and
    implement the `send` method.

    Each provider is responsible for delivering notifications
    through a specific communication channel.

    The public `send` method always runs as a Celery background task.
    Subclasses must implement `_send` only.
    """

    def __init__(self,notification: NotificationUser) -> None:
        self.notification = notification


    def send(self) -> None:
        """
        Public method used to send a notification.

        This method queues the actual sending logic on Celery.
        Subclasses MUST NOT override this method.
        """
        provider_path = f'{type(self).__module__}.{type(self).__qualname__}'
        notification_id = self.notification.pk
        transaction.on_commit(lambda: send_notification_via_provider.delay(provider_path, notification_id))

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
        logger.error(
            'Notification provider %s failed for notif_id=%s: %s',
            type(self).__name__, getattr(notification, 'pk', None), exc,
            exc_info=True,
        )

