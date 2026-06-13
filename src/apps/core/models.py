import jdatetime

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.utils.functional import LazyObject
from django.contrib.auth import get_user_model
from django.db import models

class UserModelLazy(LazyObject):

    def _setup(self):
        self._wrapped = get_user_model()

class BaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ('-id',)

    def get_created_at(self):
        return self.created_at.strftime('%Y-%m-%d %H:%M')

    def get_created_at_only_date(self):
        return self.created_at.strftime('%Y-%m-%d')

    def get_created_at_only_day(self):
        return self.created_at.strftime('%H:%M')

    def get_updated_at(self):
        return self.updated_at.strftime('%Y-%m-%d %H:%M')

    def get_created_at_jalali(self):
        if not self.created_at:
            return None
        # Convert Gregorian datetime to Jalali datetime
        jdt = jdatetime.datetime.fromgregorian(datetime=self.created_at)
        return jdt.strftime('%Y/%m/%d %H:%M:%S')

class BaseModelObjectRelation(models.Model):
    content_type_rel = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True)
    object_id_rel = models.PositiveIntegerField(null=True, blank=True)
    content_object = GenericForeignKey('content_type_rel', 'object_id_rel')

    class Meta:
        abstract = True

    @property
    def object_linked(self):
        return self.content_object

    def get_object_linked_repr(self):
        return f'{self.content_type_rel.name} | {self.object_linked}'


