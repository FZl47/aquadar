from django.conf import settings
from django.core.mail import send_mail

from apps.notification.models import NotificationUser

from .base import BaseProvider


class EmailProvider(BaseProvider):
    """
    Email notification provider.

    Sends notifications via email using Django's built-in `send_mail` function.

    The actual sending is executed asynchronously via the BaseProvider `send` method.
    """

    def _send(self, notification: NotificationUser):
        """
        Send an email notification to the target user.

        Args:
            notification (NotificationUser): Notification instance containing
                title, description, and recipient information.

        Notes:
            - Uses Django's `send_mail`.
            - From email is taken from `settings.EMAIL_HOST_USER`.
            - Recipient email is taken from `notification.to_user.email`.
        """
        subject = notification.title
        content = notification.description
        from_email = settings.EMAIL_HOST_USER
        to_email = [notification.to_user.email]

        send_mail(subject, content, from_email, to_email)
