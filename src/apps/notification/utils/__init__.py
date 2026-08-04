import pytz
from datetime import datetime

from apps.notification import models

from .mixins import NotificationModelMixin


def create_user_notif(to_user, type_notif, title, description=None, image=None, kwargs_notif=None, send_notify=True,
                      **kwargs):

    time = pytz.timezone('Asia/Tehran')
    time = datetime.now(time)
    time = f'{time.hour}:{time.minute}'
    if kwargs_notif is None:
        kwargs_notif = {}
    kwargs_notif.setdefault('time', time)

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
