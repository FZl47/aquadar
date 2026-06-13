from django.contrib import admin

from . import models

admin.site.register(models.NotificationConfig)
admin.site.register(models.NotificationUser)
