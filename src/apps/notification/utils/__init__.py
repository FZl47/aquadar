from apps.notification import models

from .mixins import NotificationModelMixin


def create_user_notif(to_user, type_notif, title, description=None, image=None, kwargs_notif=None, send_notify=True,
                      **kwargs):
    return models.NotificationUser.objects.create(
        to_user=to_user,
        title=title,
        type=type_notif,
        image=image,
        description=description,
        kwargs=kwargs_notif,
        send_notify=send_notify,
        **kwargs
    )
