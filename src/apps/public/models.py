import datetime
import statistics

from django.utils.translation import gettext_lazy as _
from django.db import models
from django.utils import timezone
from django.urls import reverse_lazy

from apps.core.models import BaseModel, UserModelLazy

User = UserModelLazy()


class RunSettings(BaseModel):
    wind_speed_more_t = models.IntegerField(verbose_name=_('Max wind speed'))
    wind_speed_less_t = models.IntegerField(verbose_name=_('Min wind speed'))
    temp_value_more_t = models.IntegerField(verbose_name=_('Max temperature'))
    temp_value_less_t = models.IntegerField(verbose_name=_('Min temperature'))
    expiration_run_time = models.IntegerField(help_text=_('By hour'), verbose_name=_('Expiration run time'))
    create_report_to_supervisor_if_has_problem = models.BooleanField(
        default=True, verbose_name=_('Create report to supervisor if has problem'))
    avg_tolerance_run_duration = models.SmallIntegerField(
        help_text=_('By minute'), verbose_name=_('Avg tolerance run duration'))
    require_gps = models.BooleanField(
        default=True, help_text=_('GPS required for start/end irrigation'), verbose_name=_('Require GPS'))
    allow_code_entry = models.BooleanField(
        default=True, help_text=_('Allow waterman to register irrigation by outlet code'),
        verbose_name=_('Allow code entry'))

    class Meta:
        verbose_name = _('Run Settings')
        verbose_name_plural = _('Run Settings')


class Farm(BaseModel):
    number = models.PositiveIntegerField(verbose_name=_('Number'))
    name = models.CharField(max_length=100, verbose_name=_('Name'))
    pool_size = models.PositiveBigIntegerField(default=0, verbose_name=_('Pool Size'))
    discharge_rate = models.DecimalField(decimal_places=2, max_digits=12, default=0, verbose_name=_('Discharge Rate'))
    is_active = models.BooleanField(default=True, verbose_name=_('Active'))

    class Meta:
        verbose_name = _('Farm')
        verbose_name_plural = _('Farms')

    def __str__(self):
        return self.name

    def get_zones(self):
        return self.zones.all()

    def get_supervisors(self):
        try:
            return self.farmusergroup.supervisors.all()
        except AttributeError:
            return []


class Zone(BaseModel):
    number = models.PositiveIntegerField(verbose_name=_('Number'))
    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name='zones', verbose_name=_('Farm'))
    name = models.CharField(max_length=100, verbose_name=_('Name'))
    order = models.PositiveIntegerField(default=0, verbose_name=_('Order'))

    class Meta:
        ordering = ['order', 'id']
        verbose_name = _('Zone')
        verbose_name_plural = _('Zones')

    def __str__(self):
        return f"{self.farm} | {self.name}"

    def get_absolute_url(self):
        return reverse_lazy('public:zone__detail', args=(self.id,))

    def get_plots(self):
        return self.plots.all()


class Plot(BaseModel):
    number = models.PositiveIntegerField(verbose_name=_('Number'))
    name = models.CharField(max_length=100, verbose_name=_('Name'))
    zone = models.ForeignKey(Zone, on_delete=models.CASCADE, related_name='plots', verbose_name=_('Zone'))
    avg_run_duration = models.SmallIntegerField(help_text=_('By minute'), verbose_name=_('Avg Duration (min)'))
    gps_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True,
                                  verbose_name=_('GPS Latitude'))
    gps_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True,
                                  verbose_name=_('GPS Longitude'))
    boundary = models.JSONField(default=list, blank=True, verbose_name=_('Plot Boundary'),
                                help_text=_('List of [lat, lng] points forming the plot polygon'))

    class Meta:
        verbose_name = _('Plot')
        verbose_name_plural = _('Plots')

    def __str__(self):
        return f"{self.name} ({self.zone.name})"

    def save(self, *args, **kwargs):
        if self.boundary:
            try:
                pts = [(float(p[0]), float(p[1])) for p in self.boundary if len(p) == 2]
                if pts:
                    self.gps_lat = sum(p[0] for p in pts) / len(pts)
                    self.gps_lng = sum(p[1] for p in pts) / len(pts)
            except (TypeError, ValueError, IndexError):
                pass
        super().save(*args, **kwargs)

    @property
    def has_running_action(self):
        return Run.objects.filter(outlet__plot=self, status='open').exists()

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

    def stop_run_group(self):
        """Stop active irrigation by creating end RunStatus for each running run (preserves data)."""
        active = self.run_groups.is_active().first()
        if active:
            for run in active.run_set.all():
                if not run.status_end:
                    start = run.status_start
                    RunStatus.objects.create(
                        run=run, status='end',
                        gps_lat=start.gps_lat if start else None,
                        gps_lng=start.gps_lng if start else None,
                    )
            active.status = 'completed'
            active.save(update_fields=['status'])
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

    def get_vegetation_soil_reports(self):
        return self.vegetation_soil_reports.all()


class Outlet(BaseModel):
    number = models.PositiveIntegerField(verbose_name=_('Number'))
    plot = models.ForeignKey(Plot, on_delete=models.CASCADE, related_name='outlets', verbose_name=_('Plot'))

    class Meta:
        verbose_name = _('Outlet')
        verbose_name_plural = _('Outlets')

    def __str__(self):
        return f"{self.number} ({self.plot.name})"

    @property
    def run(self):
        return self.runs.filter(status='open').first()

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
        if run.status_start and not run.status_end:
            return 'running'
        if run.status_start and run.status_end:
            return 'completed'
        return 'not_started'

    @property
    def last_run_status_label(self):
        d = {
            'not_started': _('Not Started'),
            'running': _('Running'),
            'completed': _('Completed'),
        }
        return d.get(self.last_run_status, '')

    def _get_active_group_run(self):
        """Return this outlet's run in the active session group, or None."""
        active_group = self.plot.run_groups.is_active().first()
        if active_group:
            return self.runs.filter(group=active_group).first()
        return None

    @property
    def status_start(self):
        run = self.run  # open run
        if run:
            return run.status_start
        group_run = self._get_active_group_run()
        return group_run.status_start if group_run else None

    @property
    def status_end(self):
        run = self.run  # open run
        if run:
            return run.status_end
        group_run = self._get_active_group_run()
        return group_run.status_end if group_run else None

    @property
    def status(self):
        run = self.run  # open run
        if run:
            return 'running'
        group_run = self._get_active_group_run()
        if group_run and group_run.status == 'closed':
            return 'completed'
        return 'not_started'

    @property
    def status_label(self):
        d = {
            'not_started': _('Not Started'),
            'running': _('Running'),
            'completed': _('Completed'),
        }
        return d.get(self.status, '')


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
    status = models.CharField(max_length=14, choices=STATUS_TYPES, verbose_name=_('Status'))
    plot = models.ForeignKey(Plot, on_delete=models.CASCADE, related_name='run_groups', verbose_name=_('Plot'))

    objects = RunGroupQuerySet.as_manager()

    class Meta:
        verbose_name = _('Run Group')
        verbose_name_plural = _('Run Groups')

    def get_runs(self):
        return self.run_set.all()

    def get_completed_runs(self):
        return self.run_set.filter(runstatus__status='end')


class Run(BaseModel):
    STATUS_TYPES = (
        ('open', _('Open')),
        ('closed', _('Closed')),
    )
    group = models.ForeignKey('RunGroup', on_delete=models.CASCADE, null=True, verbose_name=_('Run Group'))
    outlet = models.ForeignKey(Outlet, on_delete=models.CASCADE, related_name='runs', verbose_name=_('Outlet'))
    created_by = models.ForeignKey('account.User', on_delete=models.SET_NULL, null=True, blank=True,
                                   verbose_name=_('Created By'))
    is_anomalous_short = models.BooleanField(default=False, verbose_name=_('Short anomaly'))
    is_anomalous_long = models.BooleanField(default=False, verbose_name=_('Long anomaly'))
    status = models.CharField(
        max_length=8, choices=STATUS_TYPES, default='open', db_index=True, verbose_name=_('Status')
    )

    class Meta:
        verbose_name = _('Run')
        verbose_name_plural = _('Runs')

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
        avg_duration_sec = self.outlet.plot.get_avg_duration_outlets_run()
        if not avg_duration_sec:
            return None

        settings_obj = RunSettings.objects.first()
        if not settings_obj:
            return None

        run_duration_min = self.duration_seconds / 60
        avg_duration_min = avg_duration_sec / 60
        tolerance_min = settings_obj.avg_tolerance_run_duration
        lower_bound = avg_duration_min - tolerance_min
        upper_bound = avg_duration_min + tolerance_min

        return lower_bound <= run_duration_min <= upper_bound

    def report_irrigation_bad(self):
        farm = self.outlet.plot.zone.farm
        zone = self.outlet.plot.zone
        plot = self.outlet.plot
        outlet = self.outlet
        supervisors = farm.get_supervisors()
        if not supervisors:
            supervisors = User.objects.filter(is_superuser=True)
        if not supervisors:
            return None

        avg_duration_sec = plot.get_avg_duration_outlets_run()
        avg_duration_min = round(avg_duration_sec / 60, 1) if avg_duration_sec else 0
        run_duration_min = round((self.duration_seconds or 0) / 60, 1)
        settings_obj = RunSettings.objects.first()
        tolerance_min = settings_obj.avg_tolerance_run_duration if settings_obj else 0
        lower_bound = round(avg_duration_min - tolerance_min, 1)
        upper_bound = round(avg_duration_min + tolerance_min, 1)
        deviation = round(abs(run_duration_min - avg_duration_min), 1)

        if run_duration_min < lower_bound:
            self.is_anomalous_short = True
            self.save(update_fields=['is_anomalous_short'])
            description = _(
                'Abnormal irrigation duration detected for farm %(farm)s, zone %(zone)s, plot %(plot)s, '
                'outlet %(outlet)s. Actual duration: %(actual)s minutes. '
                'Expected duration: %(avg)s minutes (tolerance: ±%(tolerance)s minutes, '
                'acceptable range: %(lower)s–%(upper)s minutes). '
                'The irrigation was shorter than expected by %(deviation)s minutes. '
                'This report was automatically generated by the system because the irrigation duration was below the acceptable range.'
            ) % {
                'farm': farm.name, 'zone': zone.name, 'plot': plot.name, 'outlet': outlet.number,
                'actual': run_duration_min, 'avg': avg_duration_min, 'tolerance': tolerance_min,
                'lower': lower_bound, 'upper': upper_bound, 'deviation': deviation,
            }
        else:
            self.is_anomalous_long = True
            self.save(update_fields=['is_anomalous_long'])
            description = _(
                'Abnormal irrigation duration detected for farm %(farm)s, zone %(zone)s, plot %(plot)s, '
                'outlet %(outlet)s. Actual duration: %(actual)s minutes. '
                'Expected duration: %(avg)s minutes (tolerance: ±%(tolerance)s minutes, '
                'acceptable range: %(lower)s–%(upper)s minutes). '
                'The irrigation lasted longer than expected by %(deviation)s minutes. '
                'This report was automatically generated by the system because the irrigation duration exceeded the acceptable range.'
            ) % {
                'farm': farm.name, 'zone': zone.name, 'plot': plot.name, 'outlet': outlet.number,
                'actual': run_duration_min, 'avg': avg_duration_min, 'tolerance': tolerance_min,
                'lower': lower_bound, 'upper': upper_bound, 'deviation': deviation,
            }

        plot_detail_url = str(plot.get_absolute_url())
        sr = SystemReport.objects.create(
            waterman=self.created_by,
            outlet=outlet,
            title=_('Abnormal Irrigation Duration'),
            description=description,
        )
        sr.to_users.set(supervisors)
        for user in supervisors:
            user.create_notif(
                user=user,
                title=_('Abnormal Irrigation Duration'),
                type='irrigation_issue_report',
                notif_kw={
                    'waterman': self.created_by.get_full_name() if self.created_by else '',
                    'farm': farm.name,
                    'zone': zone.name,
                    'plot': plot.name,
                    'outlet': outlet.number,
                    'time': timezone.now().strftime('%Y-%m-%d %H:%M'),
                    'actual_duration_min': run_duration_min,
                    'expected_min': lower_bound,
                    'expected_max': upper_bound,
                    'avg_duration_min': avg_duration_min,
                    'tolerance_min': tolerance_min,
                    'deviation_min': deviation,
                    'detail_url': plot_detail_url,
                    'field_detail_url': plot_detail_url,
                },
            )


class RunStatus(BaseModel):
    STATUS_TYPES = (
        ('start', _('Start')),
        ('end', _('End')),
    )
    run = models.ForeignKey('Run', on_delete=models.CASCADE, verbose_name=_('Run'))
    status = models.CharField(max_length=10, choices=STATUS_TYPES, verbose_name=_('Status'))
    temperature_c = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True,
                                        verbose_name=_('Temperature (°C)'))
    gps_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True,
                                  verbose_name=_('GPS Latitude'))
    gps_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True,
                                  verbose_name=_('GPS Longitude'))
    wind_speed = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True,
                                     verbose_name=_('Wind Speed'))
    humidity = models.SmallIntegerField(null=True, blank=True, verbose_name=_('Humidity'))
    precipitation = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True,
                                        verbose_name=_('Precipitation'))
    solar_radiation = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True,
                                          verbose_name=_('Solar Radiation'))
    uv_index = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True,
                                   verbose_name=_('UV Index'))
    cloud_cover = models.SmallIntegerField(null=True, blank=True, verbose_name=_('Cloud Cover'))
    weather_fetched = models.BooleanField(default=False, verbose_name=_('Weather Fetched'))

    class Meta:
        verbose_name = _('Run Status')
        verbose_name_plural = _('Run Statuses')

    def __str__(self):
        return f"{self.run}({self.get_status_display()})"


class UserActivityReportAttachFile(BaseModel):
    file = models.FileField(upload_to='reports/', verbose_name=_('File'))
    report = models.ForeignKey('UserActivityReport', on_delete=models.CASCADE, verbose_name=_('Report'))

    class Meta:
        verbose_name = _('Report Attachment')
        verbose_name_plural = _('Report Attachments')


class UserActivityReport(BaseModel):
    created_by = models.ForeignKey('account.User', on_delete=models.SET_NULL, null=True,
                                   verbose_name=_('Created By'))
    title = models.CharField(max_length=256, verbose_name=_('Title'))
    description = models.TextField(null=True, blank=True, verbose_name=_('Description'))

    class Meta:
        verbose_name = _('Activity Report')
        verbose_name_plural = _('Activity Reports')

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
                                 related_name='system_report_watermans', verbose_name=_('Waterman'))
    to_users = models.ManyToManyField('account.User', verbose_name=_('Recipients'))
    title = models.CharField(max_length=256, verbose_name=_('Title'))
    description = models.TextField(null=True, blank=True, verbose_name=_('Description'))
    outlet = models.ForeignKey('Outlet', on_delete=models.CASCADE, verbose_name=_('Outlet'))
    priority = models.CharField(max_length=8, choices=PRIORITY_TYPES, default='high', verbose_name=_('Priority'))

    class Meta:
        verbose_name = _('System Report')
        verbose_name_plural = _('System Reports')

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
    user = models.ForeignKey('account.User', on_delete=models.CASCADE, null=True, verbose_name=_('User'))
    status = models.CharField(max_length=14, choices=STATUS_TYPES, verbose_name=_('Status'))
    report = models.ForeignKey('SystemReport', on_delete=models.CASCADE, verbose_name=_('Report'))
    note = models.TextField(null=True, verbose_name=_('Note'))

    class Meta:
        verbose_name = _('System Report Status')
        verbose_name_plural = _('System Report Statuses')


class ManureCategory(BaseModel):
    title = models.CharField(max_length=256, verbose_name=_('Title'))
    description = models.TextField(null=True, blank=True, verbose_name=_('Description'))

    class Meta:
        verbose_name = _('Manure Category')
        verbose_name_plural = _('Manure Categories')

    def __str__(self):
        return self.title


class ReportManure(BaseModel):
    created_by = models.ForeignKey('account.User', on_delete=models.SET_NULL, null=True,
                                   verbose_name=_('Created By'))
    category = models.ForeignKey('ManureCategory', on_delete=models.SET_NULL, null=True, blank=True,
                                 verbose_name=_('Category'))
    plot = models.ForeignKey('Plot', on_delete=models.CASCADE, verbose_name=_('Plot'))
    title = models.CharField(max_length=256, verbose_name=_('Title'))
    description = models.TextField(null=True, blank=True, verbose_name=_('Description'))

    class Meta:
        verbose_name = _('Manure Report')
        verbose_name_plural = _('Manure Reports')

    def __str__(self):
        return self.title


class FarmUserGroup(BaseModel):
    title = models.CharField(max_length=256, verbose_name=_('Title'))
    farm = models.OneToOneField('Farm', on_delete=models.CASCADE, verbose_name=_('Farm'))
    watermans = models.ManyToManyField('account.User', related_name='group_watermans', verbose_name=_('Watermans'))
    supervisors = models.ManyToManyField('account.User', related_name='group_supervisors',
                                         verbose_name=_('Supervisors'))

    class Meta:
        verbose_name = _('Farm User Group')
        verbose_name_plural = _('Farm User Groups')

    def __str__(self):
        return self.title


class PlotVegetationIndex(BaseModel):
    plot = models.ForeignKey('Plot', on_delete=models.CASCADE, related_name='vegetation_indices')
    ndvi = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)
    ndmi = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)
    ndre = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)
    evi = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)
    savi = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)
    msavi = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)
    source = models.CharField(max_length=100, blank=True)
    image_id = models.CharField(max_length=255, blank=True)
    pixel_count = models.PositiveIntegerField(null=True, blank=True)
    image = models.ImageField(upload_to='vegetation/', null=True, blank=True)
    satellite_image = models.ImageField(upload_to='vegetation/', null=True, blank=True)
    moisture_image = models.ImageField(upload_to='vegetation/', null=True, blank=True)
    observed_at = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ('-observed_at', '-id')
        verbose_name = _('Vegetation Index')
        verbose_name_plural = _('Vegetation Indices')

    def __str__(self):
        return f"VI {self.plot} | NDVI={self.ndvi}"


class PlotLeafAnalysis(BaseModel):
    STATUS_CHOICES = [
        ('pending', _('Pending')),
        ('analyzing', _('Analyzing')),
        ('done', _('Done')),
        ('error', _('Error')),
    ]
    plot = models.ForeignKey('Plot', on_delete=models.CASCADE, related_name='leaf_analyses',
                             null=True, blank=True)
    farm = models.ForeignKey('Farm', on_delete=models.CASCADE, related_name='leaf_analyses',
                             null=True, blank=True)
    zone = models.ForeignKey('Zone', on_delete=models.CASCADE, related_name='leaf_analyses',
                             null=True, blank=True)
    outlet = models.ForeignKey('Outlet', on_delete=models.CASCADE, related_name='leaf_analyses',
                               null=True, blank=True)
    image = models.ImageField(upload_to='leaf_analysis/')
    health_score = models.SmallIntegerField(null=True, blank=True)
    diseases = models.JSONField(default=list)
    deficiencies = models.JSONField(default=list)
    pests = models.JSONField(default=list)
    recommendations = models.JSONField(default=list)
    prevention = models.JSONField(default=list)
    urgency = models.CharField(max_length=50, blank=True)
    treatment_time = models.CharField(max_length=100, blank=True)
    summary = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='pending')
    analyzed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _('Leaf Analysis')
        verbose_name_plural = _('Leaf Analyses')

    def __str__(self):
        return f"Leaf {self.target} | {self.status} | score={self.health_score}"

    @property
    def target(self):
        return self.outlet or self.plot or self.zone or self.farm

    @property
    def target_kind(self):
        if self.outlet_id:
            return 'outlet'
        if self.plot_id:
            return 'plot'
        if self.zone_id:
            return 'zone'
        if self.farm_id:
            return 'farm'
        return ''


class PlotAIReport(BaseModel):
    plot = models.ForeignKey('Plot', on_delete=models.CASCADE, related_name='ai_reports')
    health_score = models.SmallIntegerField(null=True, blank=True)
    summary = models.TextField(blank=True)
    soil_assessment = models.TextField(blank=True)
    irrigation_assessment = models.TextField(blank=True)
    pest_risk = models.TextField(blank=True)
    leaf_summary = models.TextField(blank=True)
    season_recommendations = models.JSONField(default=list)
    risks = models.JSONField(default=list)
    data_sources = models.JSONField(default=dict)
    raw_response = models.TextField(blank=True)

    class Meta:
        verbose_name = _('Plot AI Report')
        verbose_name_plural = _('Plot AI Reports')

    def __str__(self):
        return f"AI Report {self.plot} | score={self.health_score}"


class FarmAIReport(BaseModel):
    farm = models.ForeignKey('Farm', on_delete=models.CASCADE, related_name='ai_reports')
    health_score = models.SmallIntegerField(null=True, blank=True)
    summary = models.TextField(blank=True)
    soil_assessment = models.TextField(blank=True)
    irrigation_assessment = models.TextField(blank=True)
    pest_risk = models.TextField(blank=True)
    season_recommendations = models.JSONField(default=list)
    risks = models.JSONField(default=list)
    data_sources = models.JSONField(default=dict)
    raw_response = models.TextField(blank=True)

    class Meta:
        verbose_name = _('Farm AI Report')
        verbose_name_plural = _('Farm AI Reports')

    def __str__(self):
        return f"Farm Report {self.farm} | score={self.health_score}"


class PlotVegetationSoilReport(BaseModel):
    """A vegetation/soil-moisture reading for one zone/section/point within a plot."""
    plot = models.ForeignKey('Plot', on_delete=models.CASCADE, related_name='vegetation_soil_reports')
    label = models.CharField(
        max_length=100, blank=True,
        verbose_name=_('Zone/Section/Point'),
        help_text=_('Identifier of the zone, section or point within the plot'),
    )
    moisture_score = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        verbose_name=_('Moisture score'),
        help_text=_('Normalized moisture score (0-100)'),
    )
    greenness_score = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        verbose_name=_('Greenness score'),
        help_text=_('Normalized greenness score (0-100)'),
    )
    moisture_value = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True,
        verbose_name=_('Moisture value'),
        help_text=_('Raw moisture value (sensor percentage or unit-based reading)'),
    )
    greenness_value = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True,
        verbose_name=_('Greenness value'),
        help_text=_('Raw greenness value (NDVI or similar vegetation index)'),
    )

    class Meta:
        ordering = ('-id',)
        verbose_name = _('Vegetation and Soil Moisture Report')
        verbose_name_plural = _('Vegetation and Soil Moisture Reports')

    def __str__(self):
        return f"{self.plot.name} | {self.label or '-'}"


class PlotWeather(BaseModel):
    """Standalone weather snapshot for a plot, fetched by GPS (not tied to RunStatus)."""
    SOURCE_TYPES = (
        ('scheduled', _('Scheduled')),
        ('manual', _('Manual')),
    )
    plot = models.ForeignKey('Plot', on_delete=models.CASCADE, related_name='weather_records')
    temperature_c = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    humidity = models.SmallIntegerField(null=True, blank=True)
    wind_speed = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    precipitation = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    solar_radiation = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    uv_index = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    cloud_cover = models.SmallIntegerField(null=True, blank=True)
    source = models.CharField(max_length=20, choices=SOURCE_TYPES, default='scheduled')

    class Meta:
        ordering = ('-created_at',)
        verbose_name = _('Plot Weather')
        verbose_name_plural = _('Plot Weather Records')
        indexes = [
            models.Index(fields=['plot', '-created_at']),
        ]

    def __str__(self):
        return f"Weather {self.plot.name} | {self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else '—'}"
