from django.db import models

from apps.core.models import BaseModel

from .providers.registry import PROVIDER_CHOICES


class AISettings(BaseModel):
    main_provider = models.CharField(
        max_length=32, choices=PROVIDER_CHOICES, blank=True, default='',
        verbose_name='ارائه‌دهنده اصلی هوش مصنوعی',
        help_text='در صورت خالی بودن، مقدار پیش‌فرض فایل تنظیمات استفاده می‌شود',
    )

    class Meta:
        verbose_name = 'تنظیمات هوش مصنوعی'
        verbose_name_plural = 'تنظیمات هوش مصنوعی'

    def __str__(self):
        return 'تنظیمات هوش مصنوعی'

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj


class ExperimentAnalysis(BaseModel):
    STATUS_PENDING = 'pending'
    STATUS_ANALYZING = 'analyzing'
    STATUS_DONE = 'done'
    STATUS_ERROR = 'error'
    STATUS_CHOICES = (
        (STATUS_PENDING, 'در صف'),
        (STATUS_ANALYZING, 'در حال تحلیل'),
        (STATUS_DONE, 'انجام شده'),
        (STATUS_ERROR, 'خطا'),
    )
    URGENCY_CHOICES = (
        ('low', 'کم'),
        ('medium', 'متوسط'),
        ('high', 'بالا'),
        ('critical', 'بحرانی'),
    )

    experiment = models.ForeignKey(
        'public.Experiment', on_delete=models.CASCADE, related_name='analyses', verbose_name='آزمایش')
    requested_by = models.ForeignKey(
        'account.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='experiment_analyses', verbose_name='درخواست‌کننده')
    provider = models.CharField(max_length=32, choices=PROVIDER_CHOICES, verbose_name='ارائه‌دهنده')
    model_name = models.CharField(max_length=128, blank=True, default='', verbose_name='مدل')
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING, verbose_name='وضعیت')
    urgency = models.CharField(max_length=16, choices=URGENCY_CHOICES, blank=True, default='', verbose_name='اولویت')
    summary = models.TextField(blank=True, default='', verbose_name='خلاصه')
    result = models.JSONField(default=dict, blank=True, verbose_name='نتیجه تحلیل')
    raw_response = models.TextField(blank=True, default='', verbose_name='پاسخ خام')
    error_message = models.TextField(blank=True, default='', verbose_name='پیام خطا')
    analyzed_at = models.DateTimeField(null=True, blank=True, verbose_name='زمان تحلیل')

    class Meta:
        ordering = ('-id',)
        verbose_name = 'تحلیل آزمایش'
        verbose_name_plural = 'تحلیل آزمایشات'

    def __str__(self):
        return f'{self.experiment} | {self.get_provider_display()}'

    @property
    def is_finished(self):
        return self.status in (self.STATUS_DONE, self.STATUS_ERROR)
