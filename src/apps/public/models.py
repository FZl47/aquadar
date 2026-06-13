import datetime
import statistics

from django.utils.translation import gettext_lazy as _
from django.db import models
from django.utils import timezone
from django.urls import reverse_lazy

from apps.core.models import BaseModel, UserModelLazy

User = UserModelLazy()


class RunSettings(BaseModel):
    wind_speed_more_t = models.IntegerField()
    wind_speed_less_t = models.IntegerField()
    temp_value_more_t = models.IntegerField()
    temp_value_less_t = models.IntegerField()
    expiration_run_time = models.IntegerField(help_text='By hour')
    create_report_to_supervisor_if_has_problem = models.BooleanField(default=True)
    avg_tolerance_run_duration = models.SmallIntegerField(help_text='By minute')
    require_gps = models.BooleanField(default=True, help_text='GPS required for start/end irrigation')
    allow_code_entry = models.BooleanField(default=True,
                                           help_text='Allow waterman to register irrigation by outlet code')


class Farm(BaseModel):
    number = models.PositiveIntegerField()
    name = models.CharField(max_length=100)
    pool_size = models.PositiveBigIntegerField(default=0)
    discharge_rate = models.DecimalField(decimal_places=2, max_digits=12, default=0)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

    def get_consumed(self):
        return 10

    def get_zones(self):
        return self.zones.all()

    def get_supervisors(self):
        try:
            return self.farmusergroup.supervisors.all()
        except AttributeError:
            return []


class Zone(BaseModel):
    number = models.PositiveIntegerField()
    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name='zones')
    name = models.CharField(max_length=100)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f"{self.farm} | {self.name}"

    def get_absolute_url(self):
        return reverse_lazy('public:zone__detail', args=(self.id,))

    def get_plots(self):
        return self.plots.all()


class Plot(BaseModel):
    number = models.PositiveIntegerField()
    name = models.CharField(max_length=100)
    zone = models.ForeignKey(Zone, on_delete=models.CASCADE, related_name='plots')
    avg_run_duration = models.SmallIntegerField(help_text='By minute')

    def __str__(self):
        return f"{self.name} ({self.zone.name})"

    @property
    def has_running_action(self):
        return RunGroup.objects.filter(plot=self, status='running').exists()

    def get_absolute_url(self):
        return reverse_lazy('public:plot_detail', args=(self.id,))

    def get_or_create_active_run_group(self):
        run_groups = self.run_groups.is_active()
        active_run = run_groups.first()
        if not active_run:
            active_run = RunGroup.objects.create(plot=self, status='running')
        return active_run

    def cancel_run_group(self):
        active = self.run_groups.is_active().first()
        if active:
            active.status = 'canceled'
            active.save(update_fields=['status'])
            active.run_set.all().delete()
        return active

    def get_outlets(self):
        return self.outlets.all()

    def get_avg_duration_outlets_run(self):
        # Return avg duration by seconds
        if self.avg_run_duration:
            return self.avg_run_duration * 60
        runs = Run.objects.filter(outlet__plot=self, runstatus__status='end')
        durations = [run.duration_seconds for run in runs if run.duration_seconds]
        if not durations:
            return 0
        return statistics.fmean(durations)


class Outlet(BaseModel):
    number = models.PositiveIntegerField()
    plot = models.ForeignKey(Plot, on_delete=models.CASCADE, related_name='outlets')

    def __str__(self):
        return f"{self.number} ({self.plot.name})"

    @property
    def run(self):
        return self.runs.filter(group__status='running').first()

    @property
    def last_run(self):
        return self.runs.first()

    @property
    def last_run_status_start(self):
        run = self.last_run
        if not run:
            return None
        return run.status_start

    @property
    def last_run_status_end(self):
        run = self.last_run
        if not run:
            return None
        return run.status_end

    @property
    def last_run_status(self):
        run = self.last_run
        if not run:
            return 'not_started'

        start = run.status_start
        end = run.status_end

        if run and not end:
            return 'running'

        if run and start and end:
            return 'completed'

        return None

    @property
    def last_run_status_label(self):
        d = {
            'not_started': _('Not Started'),
            'running': _('Running'),
            'completed': _('Completed'),
        }
        return d[self.last_run_status]

    @property
    def status_start(self):
        run = self.run
        if not run:
            return None
        return run.status_start

    @property
    def status_end(self):
        run = self.run
        if not run:
            return None
        return run.status_end

    @property
    def status(self):
        run = self.run
        if not run:
            return 'not_started'

        start = run.status_start
        end = run.status_end

        if run and not end:
            return 'running'

        if run and start and end:
            return 'completed'

        return None

    @property
    def status_label(self):
        d = {
            'not_started': _('Not Started'),
            'running': _('Running'),
            'completed': _('Completed'),
        }
        return d[self.status]


class RunGroupQuerySet(models.QuerySet):

    def is_active(self):
        now = timezone.now()
        settings_obj = RunSettings.objects.first()
        expiration_hours = settings_obj.expiration_run_time if settings_obj else 24
        return self.annotate(
            expire_time=models.ExpressionWrapper(
                models.F('created_at') + datetime.timedelta(hours=expiration_hours),
                output_field=models.DateTimeField()
            )
        ).filter(expire_time__gt=now, status='running')


class RunGroup(BaseModel):
    STATUS_TYPES = (
        ('running', _('Running')),
        ('completed', _('Completed')),
        ('canceled', _('Canceled')),
    )
    status = models.CharField(max_length=14, choices=STATUS_TYPES)
    plot = models.ForeignKey(Plot, on_delete=models.CASCADE, related_name='run_groups')

    objects = RunGroupQuerySet.as_manager()

    def get_runs(self):
        return self.run_set.all()

    def get_completed_runs(self):
        return self.run_set.filter(runstatus__status='end')


class Run(BaseModel):
    group = models.ForeignKey('RunGroup', on_delete=models.CASCADE, null=True)
    outlet = models.ForeignKey(Outlet, on_delete=models.CASCADE, related_name='runs')
    created_by = models.ForeignKey('account.User', on_delete=models.SET_NULL, null=True, blank=True)
    is_anomalous_short = models.BooleanField(default=False)
    is_anomalous_long = models.BooleanField(default=False)

    def __str__(self):
        return f"Run {self.id} on {self.outlet}"

    @property
    def status_start(self):
        return self.runstatus_set.filter(status='start').first()

    @property
    def status_end(self):
        return self.runstatus_set.filter(status='end').first()

    @property
    def duration_seconds(self):
        if self.status_start and self.status_end:
            return int((self.status_end.created_at - self.status_start.created_at).total_seconds())
        elif self.status_start and not self.status_end:
            return int((timezone.now() - self.status_start.created_at).total_seconds())
        return None

    @property
    def is_irrigation_optimal(self):
        if not self.status_end:
            return None
        avg_duration_running_per_plot = self.outlet.plot.get_avg_duration_outlets_run()

        if not avg_duration_running_per_plot:
            return None

        # Check by avg duration
        run_duration_min = self.duration_seconds / 60
        tolerance = RunSettings.objects.first().avg_tolerance_run_duration / 60
        lower_bound = avg_duration_running_per_plot - tolerance
        upper_bound = avg_duration_running_per_plot + tolerance

        return lower_bound <= run_duration_min <= upper_bound

    def report_irrigation_bad(self):
        farm = self.outlet.plot.zone.farm
        zone = self.outlet.plot.zone
        plot = self.outlet.plot
        outlet = self.outlet
        supervisors = farm.get_supervisors()
        if not supervisors:
            # Set report to admins, if has not supervisors
            supervisors = User.objects.filter(is_superuser=True)
        if not supervisors:
            return None
        sr = SystemReport.objects.create(
            waterman=self.created_by,
            outlet=self.outlet,
            title=_('Irrigation Issue'),
            description=_(
                'An issue was detected in irrigation for farm %(farm)s, zone %(zone)s, plot %(plot)s, and outlet %(outlet)s. Please check and resolve it as soon as possible.'
            ) % {'farm': farm.name, 'zone': zone.name, 'plot': plot.name, 'outlet': outlet.number}
        )
        sr.to_users.set(supervisors)
        for user in supervisors:
            user.create_notif(user=user, title=_('Irrigation Issue'), type='irrigation_issue_report',notif_kw={
                'waterman': self.created_by.get_full_name(),
                'farm': farm.name,
                'zone': zone.name,
                'plot': plot.name,
                'outlet': outlet.number,
                'time': timezone.now().strftime('%Y-%m-%d %H:%M'),
            })


class RunStatus(BaseModel):
    STATUS_TYPES = (
        ('start', _('Start')),
        ('end', _('End')),
    )
    run = models.ForeignKey('Run', on_delete=models.CASCADE)
    status = models.CharField(max_length=10, choices=STATUS_TYPES)
    temperature_c = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    gps_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    gps_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    wind_speed = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    humidity = models.SmallIntegerField(null=True, blank=True)
    weather_fetched = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.run}({self.get_status_display()})"


class UserActivityReportAttachFile(BaseModel):
    file = models.FileField(upload_to='reports/')
    report = models.ForeignKey('UserActivityReport', on_delete=models.CASCADE)


class UserActivityReport(BaseModel):
    created_by = models.ForeignKey('account.User', on_delete=models.SET_NULL, null=True)
    title = models.CharField(max_length=256)
    description = models.TextField(null=True, blank=True)

    def __str__(self):
        return self.title

    def get_attached_files(self):
        return self.useractivityreportattachfile_set.all()


class SystemReport(BaseModel):
    PRIORITY_TYPES = (
        ('low', _('Low')),
        ('medium', _('Medium')),
        ('high', _('High')),
    )
    waterman = models.ForeignKey('account.User', on_delete=models.SET_NULL, null=True,
                                 related_name='system_report_watermans')
    to_users = models.ManyToManyField('account.User')
    title = models.CharField(max_length=256)
    description = models.TextField(null=True, blank=True)
    outlet = models.ForeignKey('Outlet', on_delete=models.CASCADE)
    priority = models.CharField(max_length=8, choices=PRIORITY_TYPES, default='high')

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        is_created = self.pk is None
        super().save(*args, **kwargs)

        if is_created:
            # Create default status(pending)
            SystemReportStatus.objects.create(
                report=self,
                status='pending',
            )

    @property
    def is_resolved(self):
        return self.get_statuses().filter(status='resolved').exists()

    @property
    def last_status(self):
        return self.get_statuses().first()

    def get_absolute_url(self):
        return reverse_lazy('public:report_system__detail', args=(self.id,))

    def get_statuses(self):
        return self.systemreportstatus_set.all()


class SystemReportStatus(BaseModel):
    STATUS_TYPES = (
        ('pending', _('Pending')),
        ('in_progress', _('In Progress')),
        ('resolved', _('Resolved')),
        ('hold', _('Hold')),
    )
    user = models.ForeignKey('account.User', on_delete=models.CASCADE, null=True)
    status = models.CharField(max_length=14, choices=STATUS_TYPES)
    report = models.ForeignKey('SystemReport', on_delete=models.CASCADE)
    note = models.TextField(null=True)


class ManureCategory(BaseModel):
    title = models.CharField(max_length=256)
    description = models.TextField(null=True, blank=True)

    def __str__(self):
        return self.title


class ReportManure(BaseModel):
    created_by = models.ForeignKey('account.User', on_delete=models.SET_NULL, null=True)
    category = models.ForeignKey('ManureCategory', on_delete=models.SET_NULL, null=True, blank=True)
    plot = models.ForeignKey('Plot', on_delete=models.CASCADE)
    title = models.CharField(max_length=256)
    description = models.TextField(null=True, blank=True)

    def __str__(self):
        return self.title


class FarmUserGroup(BaseModel):
    title = models.CharField(max_length=256)
    farm = models.OneToOneField('Farm', on_delete=models.CASCADE)
    watermans = models.ManyToManyField('account.User', related_name='group_watermans')
    supervisors = models.ManyToManyField('account.User', related_name='group_supervisors')

    def __str__(self):
        return self.title
