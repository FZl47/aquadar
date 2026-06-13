import threading
import abc

from apps.notification.models import NotificationUser


class BaseProvider(abc.ABC):
    """
    Base class for all notification providers.

    This class acts as an interface that all notification providers
    (such as SMS, Email, Firebase, etc.) must inherit from and
    implement the `send` method.

    Each provider is responsible for delivering notifications
    through a specific communication channel.

    The public `send` method always runs in a separate thread.
    Subclasses must implement `_send` only.
    """

    def __init__(self,notification: NotificationUser) -> None:
        self.notification = notification


    def send(self) -> None:
        """
        Public method used to send a notification.

        This method runs the actual sending logic in a
        background thread. Subclasses MUST NOT override this method.
        """
        thread = threading.Thread(
            target=self._send_wrapper,
            args=(self.notification,),
            daemon=True
        )
        thread.start()

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
