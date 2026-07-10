import json
import uuid
from decimal import Decimal
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import (
    Avg, Case, Count, DurationField, Exists, ExpressionWrapper,
    F, OuterRef, Prefetch, Q, Subquery, Sum, Value, When,
)
from django.db.models.functions import TruncDate
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView, TemplateView, View
from django_q.tasks import async_task

from apps.core.auth.mixins import SuperVisorUserRequiredMixin, WatermanUserRequiredMixin
from apps.core.forms.utils import form_validate_err

from . import forms, models
from .models import (
    Farm, Outlet, Plot, PlotAIReport, PlotLeafAnalysis,
    PlotVegetationIndex, PlotWeather, Run, RunStatus, Zone,
    ManureCategory, ReportManure, UserActivityReport,
)
User = get_user_model()


def _redirect_with_next(request, fallback_url):
    nxt = request.POST.get('next') or request.GET.get('next')
    if nxt and nxt.startswith('/'):
        return redirect(nxt)
    return redirect(fallback_url)


def get_general_stats():
    counts = Farm.objects.filter(is_active=True).aggregate(
        total_farms=Count('id'),
        total_zones=Count('zones', distinct=True),
        total_plots=Count('zones__plots', distinct=True),
        total_outlets=Count('zones__plots__outlets', distinct=True),
    )
    return {
        'waterman_users': User.objects.filter(role='waterman'),
        'total_farms': counts['total_farms'] or 0,
        'total_zones': counts['total_zones'] or 0,
        'total_plots': counts['total_plots'] or 0,
        'total_outlets': counts['total_outlets'] or 0,
        'active_runs': Run.objects.filter(status='open').count(),
        'total_reports': UserActivityReport.objects.count(),
        'total_manure_reports': ReportManure.objects.count(),
    }


def get_runs_last_30_days():
    thirty_days_ago = timezone.now() - timedelta(days=30)
    runs_by_date = (
        Run.objects.filter(created_at__gte=thirty_days_ago)
        .annotate(date=TruncDate('created_at'))
        .values('date')
        .annotate(count=Count('id'))
        .order_by('date')
    )
    date_dict = {item['date']: item['count'] for item in runs_by_date}
    labels, data = [], []
    for i in range(30):
        day = (timezone.now() - timedelta(days=29 - i)).date()
        labels.append(day.strftime('%m/%d'))
        data.append(date_dict.get(day, 0))
    return {'labels': labels, 'data': data}


def get_run_status_distribution():
    counts = {
        item['group__status']: item['count']
        for item in Run.objects.values('group__status').annotate(count=Count('id'))
    }
    return {
        'labels': [str(_('Running')), str(_('Completed')), str(_('Canceled'))],
        'data': [counts.get('running', 0), counts.get('completed', 0), counts.get('canceled', 0)],
    }


def get_avg_duration_per_zone():
    start_sub = Subquery(
        RunStatus.objects.filter(run=OuterRef('pk'), status='start').values('created_at')[:1]
    )
    end_sub = Subquery(
        RunStatus.objects.filter(run=OuterRef('pk'), status='end').values('created_at')[:1]
    )
    zone_data = (
        Run.objects
        .annotate(start_time=start_sub, end_time=end_sub)
        .filter(start_time__isnull=False, end_time__isnull=False)
        .annotate(
            duration=ExpressionWrapper(F('end_time') - F('start_time'), output_field=DurationField())
        )
        .values('outlet__plot__zone__name')
        .annotate(avg_dur=Avg('duration'))
        .filter(avg_dur__isnull=False)
        .order_by('outlet__plot__zone__name')
    )
    labels = [z['outlet__plot__zone__name'] for z in zone_data]
    data = [round(z['avg_dur'].total_seconds() / 60, 2) for z in zone_data]
    return {'labels': labels, 'data': data}


def get_temperature_distribution():
    result = RunStatus.objects.filter(temperature_c__isnull=False).aggregate(
        t_0_10=Count(Case(When(temperature_c__lt=10, then=1))),
        t_10_20=Count(Case(When(temperature_c__gte=10, temperature_c__lt=20, then=1))),
        t_20_30=Count(Case(When(temperature_c__gte=20, temperature_c__lt=30, then=1))),
        t_30_40=Count(Case(When(temperature_c__gte=30, temperature_c__lt=40, then=1))),
        t_40_plus=Count(Case(When(temperature_c__gte=40, then=1))),
    )
    return {
        'labels': ['0-10', '10-20', '20-30', '30-40', '40+'],
        'data': [result['t_0_10'], result['t_10_20'], result['t_20_30'], result['t_30_40'], result['t_40_plus']],
    }


def get_gps_locations():
    locations = (
        RunStatus.objects
        .filter(gps_lat__isnull=False, gps_lng__isnull=False)
        .select_related('run__outlet__plot')
        .values('gps_lat', 'gps_lng', 'run__outlet__plot__name')
        [:200]
    )
    return [
        {
            'gps_lat': float(loc['gps_lat']),
            'gps_lng': float(loc['gps_lng']),
            'plot': loc.get('run__outlet__plot__name') or '',
        }
        for loc in locations
    ]


def get_manure_distribution():
    data = (
        ReportManure.objects
        .values('category__title')
        .annotate(total=Count('id'))
        .order_by('-total')
    )
    return {
        'labels': [item['category__title'] or 'Unknown' for item in data],
        'data': [item['total'] for item in data],
    }


class Index(TemplateView):
    templates = {
        'waterman': 'public/dashboard/waterman.html',
        'supervisor': 'public/dashboard/supervisor.html',
    }

    def _resolve_role(self):
        role = self.request.user.role
        if role not in self.templates:
            return 'supervisor' if self.request.user.is_superuser else 'waterman'
        return role

    def get_template_names(self):
        return [self.templates[self._resolve_role()]]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(getattr(self, f'get_context_{self._resolve_role()}')())
        return context

    def get_context_waterman(self):
        params = self.request.GET
        plot_id = params.get('plot')
        plot_obj = None
        user = self.request.user
        if plot_id and plot_id.isdigit():
            if user.is_superuser:
                plot_obj = get_object_or_404(models.Plot, id=plot_id)
            else:
                plot_obj = get_object_or_404(models.Plot, id=plot_id, zone__farm__user__in=[user])
        run_settings = models.RunSettings.objects.first()
        return {
            'plot_obj': plot_obj,
            'zones': models.Zone.objects.all(),
            'plots': models.Plot.objects.select_related('zone'),
            'active_runnings': models.Run.objects.filter(created_by=user, status='open'),
            'system_reports': models.SystemReport.objects.filter(
                to_users__in=[user]
            ).exclude(systemreportstatus__status='resolved'),
            'manure_categories': models.ManureCategory.objects.all(),
            'run_settings': run_settings,
            'require_gps': run_settings.require_gps if run_settings else True,
            'allow_code_entry': run_settings.allow_code_entry if run_settings else True,
        }

    def get_context_supervisor(self):
        stats = get_general_stats()
        runs_chart = get_runs_last_30_days()
        status_chart = get_run_status_distribution()
        duration_chart = get_avg_duration_per_zone()
        temp_chart = get_temperature_distribution()
        manure_chart = get_manure_distribution()
        gps_locations = get_gps_locations()
        run_settings = models.RunSettings.objects.first()
        _open_run_sq = models.Run.objects.filter(group=OuterRef('pk'), status='open')
        active_groups = (
            models.RunGroup.objects.filter(Exists(_open_run_sq))
            .select_related('plot__zone__farm')
            .prefetch_related('run_set__outlet')
            [:20]
        )
        return {
            **stats,
            'runs_labels': json.dumps(runs_chart['labels']),
            'runs_data': json.dumps(runs_chart['data']),
            'status_labels': json.dumps(status_chart['labels']),
            'status_data': json.dumps(status_chart['data']),
            'duration_labels': json.dumps(duration_chart['labels']),
            'duration_data': json.dumps(duration_chart['data']),
            'temp_labels': json.dumps(temp_chart['labels']),
            'temp_data': json.dumps(temp_chart['data']),
            'manure_labels': json.dumps(manure_chart['labels']),
            'manure_data': json.dumps(manure_chart['data']),
            'gps_locations': json.dumps(gps_locations),
            'run_settings': run_settings,
            'active_groups': active_groups,
            'farms': Farm.objects.all(),
            'zones': Zone.objects.select_related('farm').all(),
            'plots': Plot.objects.select_related('zone__farm').all(),
            'outlets': Outlet.objects.select_related('plot__zone__farm').all(),
            'unresolved_system_reports': models.SystemReport.objects.select_related(
                'outlet__plot__zone__farm'
            ).exclude(systemreportstatus__status='resolved'),
        }


class PlotOutletActionByCode(WatermanUserRequiredMixin, View):

    def get_redirect_url(self):
        return self.request.META.get('HTTP_REFERER', reverse_lazy('public:index'))

    def get(self, request):
        outlet_code = request.GET.get('outlet_code')
        if not outlet_code:
            messages.warning(request, _('Code number is empty'))
            return redirect(self.get_redirect_url())

        outlet_code_normalized = outlet_code.split('-')
        if len(outlet_code_normalized) != 3:
            messages.warning(request, _('Code number is invalid'))
            return redirect(self.get_redirect_url())

        farm_number, zone_number, outlet_number = outlet_code_normalized
        user = request.user
        qs = models.Outlet.objects.filter(
            plot__zone__farm__number=farm_number,
            plot__zone__number=zone_number,
            number=outlet_number,
        )
        if not user.is_superuser:
            qs = qs.filter(plot__zone__farm__user__in=[user])

        outlet_obj = qs.first()
        if not outlet_obj:
            messages.warning(request, _('Code number is wrong'))
            return redirect(self.get_redirect_url())

        redirect_url = reverse('public:plot_outlet_action', args=(outlet_obj.id,))
        gps_lat = request.GET.get('gps_lat', '')
        gps_lng = request.GET.get('gps_lng', '')
        if gps_lat and gps_lng:
            redirect_url += f'?gps_lat={gps_lat}&gps_lng={gps_lng}'
        return redirect(redirect_url)


class PlotOutletAction(WatermanUserRequiredMixin, View):

    def get_redirect_url(self):
        return self.request.META.get('HTTP_REFERER', reverse_lazy('public:index'))

    def _get_gps(self, request):
        params = request.POST if request.method == 'POST' else request.GET
        try:
            lat = params.get('gps_lat')
            lng = params.get('gps_lng')
            if lat and lng:
                return float(lat), float(lng)
        except (ValueError, TypeError):
            pass
        return None, None

    _status_labels = {
        'not_started': _('Not Started'),
        'running': _('Running'),
        'completed': _('Completed'),
    }

    def dispatch(self, request, outlet_id):
        super().dispatch(request, outlet_id)
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        user = request.user
        if user.is_superuser:
            outlet_obj = get_object_or_404(models.Outlet, id=outlet_id)
        else:
            outlet_obj = get_object_or_404(models.Outlet, id=outlet_id, plot__zone__farm__user__in=[user])

        gps_lat, gps_lng = self._get_gps(request)
        plot = outlet_obj.plot

        run_settings = models.RunSettings.objects.first()
        require_gps = run_settings.require_gps if run_settings else True

        if outlet_obj.status == 'not_started':
            if require_gps and (gps_lat is None or gps_lng is None):
                msg = str(_('Location (GPS) is required to start irrigation. Please enable location services.'))
                if is_ajax:
                    return JsonResponse({'success': False, 'message': msg})
                messages.error(request, msg)
                return redirect(self.get_redirect_url())
            run_group = plot.get_or_create_active_run_group()
            run_obj = models.Run.objects.create(group=run_group, created_by=user, outlet=outlet_obj)
            models.RunStatus.objects.create(run=run_obj, status='start', gps_lat=gps_lat, gps_lng=gps_lng)
            msg = str(_('The run has started'))
            new_status = 'running'
            if is_ajax:
                return JsonResponse({
                    'success': True, 'message': msg,
                    'outlet_status': new_status,
                    'outlet_status_label': str(self._status_labels[new_status]),
                    'outlet_id': outlet_id,
                })
            messages.success(request, msg)
        elif outlet_obj.status == 'running':
            run_obj = outlet_obj.run
            models.RunStatus.objects.create(run=run_obj, status='end', gps_lat=gps_lat, gps_lng=gps_lng)
            run_group = run_obj.group
            outlets_count = plot.get_outlets().count()
            completed_runs_count = run_group.get_completed_runs().count()
            all_done = outlets_count == completed_runs_count
            if all_done:
                run_group.status = 'completed'
                run_group.save(update_fields=['status'])
                msg = str(_('The run operation has completed'))
                new_status = 'not_started'
            else:
                msg = str(_('The run has stopped'))
                new_status = 'completed'
            if is_ajax:
                return JsonResponse({
                    'success': True, 'message': msg,
                    'outlet_status': new_status,
                    'outlet_status_label': str(self._status_labels[new_status]),
                    'outlet_id': outlet_id,
                })
            messages.success(request, msg)
        else:
            msg = str(_('The run has already completed'))
            if is_ajax:
                return JsonResponse({
                    'success': True, 'message': msg,
                    'outlet_status': outlet_obj.status,
                    'outlet_status_label': str(self._status_labels.get(outlet_obj.status, '')),
                    'outlet_id': outlet_id,
                })
            messages.success(request, msg)
        return redirect(self.get_redirect_url())


class PlotOutletsRunReset(WatermanUserRequiredMixin, View):

    def get_redirect_url(self):
        return self.request.META.get('HTTP_REFERER', reverse_lazy('public:index'))

    def get(self, request, plot_id):
        user = self.request.user
        if user.is_superuser:
            plot_obj = get_object_or_404(models.Plot, id=plot_id)
        else:
            plot_obj = get_object_or_404(models.Plot, id=plot_id, zone__farm__user__in=[user])
        plot_obj.cancel_run_group()
        messages.success(request, _('The operation was successfully'))
        return redirect(self.get_redirect_url())


class SystemReportDetail(View):
    template_name = 'public/report/system/detail.html'
    form = forms.SystemReportStatusForm

    def _check_access(self, request, report):
        user = request.user
        if user.is_superuser or user.role == 'supervisor':
            return True
        return report.to_users.filter(id=user.id).exists()

    def get(self, request, pk):
        report = get_object_or_404(models.SystemReport, pk=pk)
        if not self._check_access(request, report):
            raise Http404
        return render(request, self.template_name, {
            'report': report,
            'statuses': report.get_statuses().select_related('user'),
        })

    def post(self, request, pk):
        report = get_object_or_404(models.SystemReport, pk=pk)
        if not self._check_access(request, report):
            raise Http404
        data = request.POST.copy()
        data['user'] = request.user
        data['report'] = report
        f = self.form(data)
        if not form_validate_err(request, f):
            return redirect(report.get_absolute_url())
        f.save()
        messages.success(request, _('Your report status has been submit successfully'))
        return redirect(report.get_absolute_url())


class ZoneDetail(SuperVisorUserRequiredMixin, DetailView):
    model = Zone
    template_name = 'public/zone/detail.html'
    context_object_name = 'zone'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['farms'] = Farm.objects.all()
        zone = self.object
        start_sub = Subquery(
            RunStatus.objects.filter(run=OuterRef('pk'), status='start').values('created_at')[:1]
        )
        end_sub = Subquery(
            RunStatus.objects.filter(run=OuterRef('pk'), status='end').values('created_at')[:1]
        )
        qs = (
            Run.objects.filter(outlet__plot__zone=zone)
            .annotate(start_time=start_sub, end_time=end_sub)
            .exclude(start_time__isnull=True, end_time__isnull=True)
            .annotate(
                day=TruncDate('end_time'),
                duration=ExpressionWrapper(F('end_time') - F('start_time'), output_field=DurationField()),
            )
            .exclude(end_time__isnull=True)
            .values('day')
            .annotate(total_duration=Sum('duration'))
            .order_by('day')
        )
        outlets = Outlet.objects.filter(plot__zone=zone)
        context['plots_count'] = zone.get_plots().count()
        context['outlets_count'] = outlets.count()
        context['runs_count'] = Run.objects.filter(outlet__plot__zone=zone).count()
        context['reports_count'] = models.SystemReport.objects.filter(outlet__plot__zone=zone).count()
        context['manure_count'] = ReportManure.objects.filter(plot__zone=zone).count()
        context['chart_labels'] = [x['day'].strftime('%Y-%m-%d') for x in qs]
        context['chart_data'] = [round(x['total_duration'].total_seconds() / 60, 2) for x in qs]
        context['leaf_analyses'] = zone.leaf_analyses.order_by('-created_at')[:6]
        context['leaf_upload_url'] = reverse('public:zone_leaf_upload', args=[zone.pk])
        context['leaf_list_url'] = reverse('public:zone_leaf_list', args=[zone.pk])
        return context


def get_plot_outlet_water_data(plot_id):
    plot = get_object_or_404(
        Plot.objects.select_related('zone__farm'),
        id=plot_id,
    )
    farm = plot.zone.farm
    discharge_rate = farm.discharge_rate or Decimal('0')

    last_group = plot.run_groups.exclude(status='canceled').order_by('-created_at').first()

    empty_base = {
        'plot': plot,
        'farm': farm,
        'last_group': None,
        'discharge_rate': float(discharge_rate),
        'outlets': [],
        'total_plot_seconds': 0,
        'total_plot_hours': 0,
        'total_plot_liters': 0,
        'total_plot_m3': 0,
    }

    if not last_group:
        return empty_base

    now_naive = timezone.now()

    outlet_stats = (
        Run.objects.filter(outlet__plot=plot, group=last_group)
        .annotate(
            start_time=Subquery(
                RunStatus.objects.filter(run=OuterRef('pk'), status='start').values('created_at')[:1]
            ),
            end_time=Subquery(
                RunStatus.objects.filter(run=OuterRef('pk'), status='end').values('created_at')[:1]
            ),
        )
        .filter(start_time__isnull=False)
        .annotate(
            duration=ExpressionWrapper(
                Case(
                    When(end_time__isnull=False, then=F('end_time') - F('start_time')),
                    default=Value(now_naive) - F('start_time'),
                ),
                output_field=DurationField(),
            )
        )
        .values('outlet_id', 'outlet__number')
        .annotate(total_duration=Sum('duration'), run_count=Count('id'))
        .order_by('outlet__number')
    )

    open_outlet_ids = set(
        Run.objects.filter(outlet__plot=plot, group=last_group, status='open').values_list('outlet_id', flat=True)
    )

    outlet_rows = []
    total_plot_seconds = 0
    total_plot_liters = Decimal('0')

    for row in outlet_stats:
        total_seconds = int(row['total_duration'].total_seconds()) if row['total_duration'] else 0
        total_liters = Decimal(total_seconds) * discharge_rate
        total_plot_seconds += total_seconds
        total_plot_liters += total_liters
        irr_status = 'running' if row['outlet_id'] in open_outlet_ids else 'completed'
        outlet_rows.append({
            'outlet_id': row['outlet_id'],
            'outlet_number': row['outlet__number'],
            'run_count': row['run_count'],
            'status': irr_status,
            'total_seconds': total_seconds,
            'total_minutes': round(total_seconds / 60, 2),
            'total_hours': round(total_seconds / 3600, 2),
            'total_liters': round(float(total_liters), 2),
            'total_m3': round(float(total_liters / Decimal('1000')), 3),
        })

    return {
        'plot': plot,
        'farm': farm,
        'last_group': last_group,
        'discharge_rate': float(discharge_rate),
        'outlets': outlet_rows,
        'total_plot_seconds': total_plot_seconds,
        'total_plot_hours': round(total_plot_seconds / 3600, 2),
        'total_plot_liters': round(float(total_plot_liters), 2),
        'total_plot_m3': round(float(total_plot_liters / Decimal('1000')), 3),
    }


def plot_outlet_discharge_view(request, plot_id):
    data = get_plot_outlet_water_data(plot_id)
    chart_labels = [f"Outlet {o['outlet_number']}" for o in data['outlets']]
    context = {
        **data,
        'chart_labels': json.dumps(chart_labels),
        'chart_water': json.dumps([o['total_m3'] for o in data['outlets']]),
        'chart_duration': json.dumps([o['total_hours'] for o in data['outlets']]),
        'chart_runs': json.dumps([o['run_count'] for o in data['outlets']]),
    }
    return render(request, 'public/overview/plot_outlet_discharge.html', context)


class UserActivityReportCreateView(WatermanUserRequiredMixin, View):
    def post(self, request):
        f = forms.UserActivityReportForm(request.POST)
        if not form_validate_err(request, f):
            return redirect(request.META.get('HTTP_REFERER', reverse_lazy('public:index')))
        report = f.save(commit=False)
        report.created_by = request.user
        report.save()
        messages.success(request, _('Report submitted successfully'))
        return redirect(request.META.get('HTTP_REFERER', reverse_lazy('public:index')))


class UserActivityReportListView(SuperVisorUserRequiredMixin, TemplateView):
    template_name = 'public/report/activity/list.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['reports'] = UserActivityReport.objects.select_related('created_by').all()
        return context


class ReportManureCreateView(WatermanUserRequiredMixin, View):
    def post(self, request, plot_id):
        user = request.user
        if user.is_superuser:
            plot_obj = get_object_or_404(models.Plot, id=plot_id)
        else:
            plot_obj = get_object_or_404(models.Plot, id=plot_id, zone__farm__user__in=[user])
        f = forms.ReportManureForm(request.POST)
        if not form_validate_err(request, f):
            return redirect(request.META.get('HTTP_REFERER', reverse_lazy('public:index')))
        report = f.save(commit=False)
        report.created_by = user
        report.plot = plot_obj
        report.save()
        messages.success(request, _('Manure report submitted successfully'))
        return redirect(request.META.get('HTTP_REFERER', reverse_lazy('public:index')))


class WatermanListView(SuperVisorUserRequiredMixin, TemplateView):
    template_name = 'public/waterman/list.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        watermans = User.objects.filter(role='waterman').prefetch_related(
            Prefetch(
                'run_set',
                queryset=Run.objects.filter(status='open').select_related(
                    'outlet__plot__zone__farm'
                ),
                to_attr='active_runs_list',
            )
        )
        waterman_data = []
        for w in watermans:
            last_weather = (
                RunStatus.objects.filter(run__created_by=w, weather_fetched=True)
                .select_related('run__outlet__plot__zone__farm')
                .order_by('-id')
                .first()
            ) or (
                RunStatus.objects.filter(run__created_by=w)
                .select_related('run__outlet__plot__zone__farm')
                .order_by('-id')
                .first()
            )
            waterman_data.append({
                'user': w,
                'active_runs': w.active_runs_list,
                'active_runs_count': len(w.active_runs_list),
                'last_weather': last_weather,
            })
        context['waterman_data'] = waterman_data
        return context


class ManureReportListView(SuperVisorUserRequiredMixin, TemplateView):
    template_name = 'public/report/manure/list.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['reports'] = models.ReportManure.objects.select_related(
            'created_by', 'category', 'plot__zone__farm'
        ).order_by('-id')
        return context


class RunListView(SuperVisorUserRequiredMixin, TemplateView):
    template_name = 'public/run/list.html'
    PER_PAGE = 20

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        page_num = self.request.GET.get('page', 1)
        qs = (
            models.Run.objects
            .select_related('outlet__plot__zone__farm', 'created_by', 'group')
            .prefetch_related('runstatus_set')
            .order_by('-id')
        )
        paginator = Paginator(qs, self.PER_PAGE)
        context['page_obj'] = paginator.get_page(page_num)
        return context


class RunDetailView(SuperVisorUserRequiredMixin, DetailView):
    model = Run
    template_name = 'public/run/detail.html'
    context_object_name = 'run'

    def get_queryset(self):
        return Run.objects.select_related(
            'outlet__plot__zone__farm', 'group', 'created_by'
        ).prefetch_related('runstatus_set')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['outlets'] = Outlet.objects.select_related('plot__zone__farm').all()
        context['users'] = User.objects.all()
        return context


class RunDeleteView(SuperVisorUserRequiredMixin, View):
    def post(self, request, pk):
        run = get_object_or_404(Run, pk=pk)
        run.delete()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True})
        messages.success(request, _('Run deleted successfully'))
        return redirect(reverse('public:run_list'))


class RunUpdateView(SuperVisorUserRequiredMixin, View):
    def post(self, request, pk):
        run = get_object_or_404(Run, pk=pk)
        f = forms.RunForm(request.POST, instance=run)
        if f.is_valid():
            f.save()
            messages.success(request, _('Run updated successfully'))
        else:
            messages.error(request, str(f.errors))
        return _redirect_with_next(request, reverse('public:run_detail', args=[pk]))


class RunStatusUpdateView(SuperVisorUserRequiredMixin, View):
    def post(self, request, pk):
        rs = get_object_or_404(RunStatus, pk=pk)
        f = forms.RunStatusForm(request.POST, instance=rs)
        if f.is_valid():
            f.save()
            messages.success(request, _('Irrigation status updated successfully'))
        else:
            messages.error(request, str(f.errors))
        return _redirect_with_next(request, reverse('public:run_detail', args=[rs.run_id]))


class RunStatusDeleteView(SuperVisorUserRequiredMixin, View):
    def post(self, request, pk):
        rs = get_object_or_404(RunStatus, pk=pk)
        run_id = rs.run_id
        rs.delete()
        messages.success(request, _('Irrigation status deleted successfully'))
        return _redirect_with_next(request, reverse('public:run_detail', args=[run_id]))


class FarmListView(SuperVisorUserRequiredMixin, TemplateView):
    template_name = 'public/farm/list.html'
    PER_PAGE = 15

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        search = self.request.GET.get('q', '').strip()
        page_num = self.request.GET.get('page', 1)
        qs = Farm.objects.annotate(
            zone_count=Count('zones', distinct=True),
            plot_count=Count('zones__plots', distinct=True),
            outlet_count=Count('zones__plots__outlets', distinct=True),
            active_run_count=Count(
                'zones__plots__outlets__runs',
                filter=Q(zones__plots__outlets__runs__status='open'),
                distinct=True,
            ),
        )
        if search:
            qs = qs.filter(name__icontains=search)
        paginator = Paginator(qs.order_by('number'), self.PER_PAGE)
        context['page_obj'] = paginator.get_page(page_num)
        context['search'] = search
        return context


class FarmDetailView(SuperVisorUserRequiredMixin, DetailView):
    model = Farm
    template_name = 'public/farm/detail.html'
    context_object_name = 'farm'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        farm = self.object
        context['zones'] = farm.get_zones().annotate(
            plot_count=Count('plots', distinct=True),
            outlet_count=Count('plots__outlets', distinct=True),
        )
        context['total_plots'] = Plot.objects.filter(zone__farm=farm).count()
        context['total_outlets'] = Outlet.objects.filter(plot__zone__farm=farm).count()
        context['active_runs'] = Run.objects.filter(
            outlet__plot__zone__farm=farm, status='open'
        ).count()
        context['leaf_analyses'] = farm.leaf_analyses.order_by('-created_at')[:6]
        context['leaf_upload_url'] = reverse('public:farm_leaf_upload', args=[farm.pk])
        context['leaf_list_url'] = reverse('public:farm_leaf_list', args=[farm.pk])
        return context


class FarmCreateView(SuperVisorUserRequiredMixin, View):
    def post(self, request):
        f = forms.FarmForm(request.POST)
        if f.is_valid():
            farm = f.save()
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True, 'id': farm.pk})
            messages.success(request, _('Farm created successfully'))
        else:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'errors': f.errors})
            messages.error(request, str(f.errors))
        return _redirect_with_next(request, reverse('public:farm_list'))


class FarmUpdateView(SuperVisorUserRequiredMixin, View):
    def post(self, request, pk):
        farm = get_object_or_404(Farm, pk=pk)
        f = forms.FarmForm(request.POST, instance=farm)
        if f.is_valid():
            f.save()
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True})
            messages.success(request, _('Farm updated successfully'))
        else:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'errors': f.errors})
            messages.error(request, str(f.errors))
        return _redirect_with_next(request, reverse('public:farm_detail', args=[pk]))


class FarmDischargeRateUpdateView(SuperVisorUserRequiredMixin, View):
    def post(self, request, pk):
        farm = get_object_or_404(Farm, pk=pk)
        try:
            rate = Decimal(request.POST.get('discharge_rate', ''))
            if rate < 0:
                raise ValueError
            farm.discharge_rate = rate
            farm.save(update_fields=['discharge_rate'])
            messages.success(request, _('Discharge rate updated successfully'))
        except Exception:
            messages.error(request, _('Invalid discharge rate value'))
        return redirect(request.META.get('HTTP_REFERER', reverse_lazy('public:index')))


class FarmDeleteView(SuperVisorUserRequiredMixin, View):
    def post(self, request, pk):
        farm = get_object_or_404(Farm, pk=pk)
        farm.delete()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True})
        messages.success(request, _('Farm deleted successfully'))
        return redirect(reverse('public:farm_list'))


class ZoneListView(SuperVisorUserRequiredMixin, TemplateView):
    template_name = 'public/zone/list.html'
    PER_PAGE = 20

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        search = self.request.GET.get('q', '').strip()
        farm_id = self.request.GET.get('farm', '').strip()
        page_num = self.request.GET.get('page', 1)
        qs = Zone.objects.select_related('farm').annotate(
            plot_count=Count('plots', distinct=True),
            outlet_count=Count('plots__outlets', distinct=True),
            active_run_count=Count(
                'plots__outlets__runs',
                filter=Q(plots__outlets__runs__status='open'),
                distinct=True,
            ),
        )
        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(farm__name__icontains=search))
        if farm_id.isdigit():
            qs = qs.filter(farm_id=farm_id)
        paginator = Paginator(qs.order_by('farm', 'order', 'id'), self.PER_PAGE)
        context['page_obj'] = paginator.get_page(page_num)
        context['search'] = search
        context['farm_id'] = farm_id
        context['farms'] = Farm.objects.all()
        return context


class ZoneCreateView(SuperVisorUserRequiredMixin, View):
    def post(self, request):
        f = forms.ZoneForm(request.POST)
        if f.is_valid():
            zone = f.save()
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True, 'id': zone.pk})
            messages.success(request, _('Zone created successfully'))
        else:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'errors': f.errors})
            messages.error(request, str(f.errors))
        return _redirect_with_next(request, reverse('public:zone_list'))


class ZoneUpdateView(SuperVisorUserRequiredMixin, View):
    def post(self, request, pk):
        zone = get_object_or_404(Zone, pk=pk)
        f = forms.ZoneForm(request.POST, instance=zone)
        if f.is_valid():
            f.save()
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True})
            messages.success(request, _('Zone updated successfully'))
        else:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'errors': f.errors})
            messages.error(request, str(f.errors))
        return _redirect_with_next(request, reverse('public:zone__detail', args=[pk]))


class ZoneDeleteView(SuperVisorUserRequiredMixin, View):
    def post(self, request, pk):
        zone = get_object_or_404(Zone, pk=pk)
        zone.delete()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True})
        messages.success(request, _('Zone deleted successfully'))
        return redirect(reverse('public:zone_list'))


class OutletListView(SuperVisorUserRequiredMixin, TemplateView):
    template_name = 'public/outlet/list.html'
    PER_PAGE = 25

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        search = self.request.GET.get('q', '').strip()
        page_num = self.request.GET.get('page', 1)
        running_subq = Run.objects.filter(outlet=OuterRef('pk'), status='open')
        qs = Outlet.objects.select_related('plot__zone__farm').annotate(
            is_running=Exists(running_subq)
        )
        if search:
            qs = qs.filter(
                Q(number__icontains=search)
                | Q(plot__name__icontains=search)
                | Q(plot__zone__name__icontains=search)
                | Q(plot__zone__farm__name__icontains=search)
            )
        paginator = Paginator(
            qs.order_by('plot__zone__farm__number', 'plot__zone__order', 'plot__number', 'number'),
            self.PER_PAGE,
        )
        context['page_obj'] = paginator.get_page(page_num)
        context['search'] = search
        return context


class OutletDetailView(SuperVisorUserRequiredMixin, DetailView):
    model = Outlet
    template_name = 'public/outlet/detail.html'
    context_object_name = 'outlet'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['runs'] = (
            Run.objects.filter(outlet=self.object)
            .select_related('group', 'created_by')
            .prefetch_related('runstatus_set')
            .order_by('-id')[:20]
        )
        context['plots'] = Plot.objects.select_related('zone__farm').all()
        context['leaf_analyses'] = self.object.leaf_analyses.order_by('-created_at')[:6]
        context['leaf_upload_url'] = reverse('public:outlet_leaf_upload', args=[self.object.pk])
        context['leaf_list_url'] = reverse('public:outlet_leaf_list', args=[self.object.pk])
        return context


class OutletCreateView(SuperVisorUserRequiredMixin, View):
    def post(self, request):
        f = forms.OutletForm(request.POST)
        if f.is_valid():
            outlet = f.save()
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True, 'id': outlet.pk})
            messages.success(request, _('Outlet created successfully'))
        else:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'errors': f.errors})
            messages.error(request, str(f.errors))
        return _redirect_with_next(request, reverse('public:outlet_list'))


class OutletUpdateView(SuperVisorUserRequiredMixin, View):
    def post(self, request, pk):
        outlet = get_object_or_404(Outlet, pk=pk)
        f = forms.OutletForm(request.POST, instance=outlet)
        if f.is_valid():
            f.save()
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True})
            messages.success(request, _('Outlet updated successfully'))
        else:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'errors': f.errors})
            messages.error(request, str(f.errors))
        return _redirect_with_next(request, reverse('public:outlet_detail', args=[pk]))


class OutletDeleteView(SuperVisorUserRequiredMixin, View):
    def post(self, request, pk):
        outlet = get_object_or_404(Outlet, pk=pk)
        outlet.delete()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True})
        messages.success(request, _('Outlet deleted successfully'))
        return redirect(reverse('public:outlet_list'))


class PlotListView(SuperVisorUserRequiredMixin, TemplateView):
    template_name = 'public/plot/list.html'
    PER_PAGE = 20

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        search = self.request.GET.get('q', '').strip()
        zone_id = self.request.GET.get('zone', '').strip()
        page_num = self.request.GET.get('page', 1)
        qs = Plot.objects.select_related('zone__farm').annotate(
            outlet_count=Count('outlets', distinct=True),
            active_run_count=Count(
                'outlets__runs',
                filter=Q(outlets__runs__status='open'),
                distinct=True,
            ),
        )
        if search:
            qs = qs.filter(
                Q(name__icontains=search)
                | Q(zone__name__icontains=search)
                | Q(zone__farm__name__icontains=search)
            )
        if zone_id.isdigit():
            qs = qs.filter(zone_id=zone_id)
        paginator = Paginator(
            qs.order_by('zone__farm__number', 'zone__order', 'zone__number', 'number'),
            self.PER_PAGE,
        )
        context['page_obj'] = paginator.get_page(page_num)
        context['search'] = search
        context['zone_id'] = zone_id
        context['zones'] = Zone.objects.select_related('farm').all()
        return context


class PlotDetailView(SuperVisorUserRequiredMixin, DetailView):
    model = Plot
    template_name = 'public/plot/detail.html'
    context_object_name = 'plot'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        plot = self.object

        pw_stats = PlotWeather.objects.filter(plot=plot).order_by('-created_at')[:10].aggregate(
            avg_temperature=Avg('temperature_c'),
            avg_wind_speed=Avg('wind_speed'),
            avg_humidity=Avg('humidity'),
        )

        start_sub = Subquery(
            RunStatus.objects.filter(run=OuterRef('pk'), status='start').values('created_at')[:1]
        )
        end_sub = Subquery(
            RunStatus.objects.filter(run=OuterRef('pk'), status='end').values('created_at')[:1]
        )
        _open_run_for_plot = models.Run.objects.filter(group=OuterRef('pk'), status='open')
        active_rg = models.RunGroup.objects.filter(
            Exists(_open_run_for_plot), plot=plot
        ).order_by('-created_at').first()
        if not active_rg:
            active_rg = models.RunGroup.objects.filter(plot=plot).order_by('-created_at').first()
        if active_rg:
            run_qs_for_water = Run.objects.filter(group=active_rg)
        else:
            run_qs_for_water = Run.objects.none()
        dur_agg = (
            run_qs_for_water
            .annotate(start_time=start_sub, end_time=end_sub)
            .filter(start_time__isnull=False, end_time__isnull=False)
            .aggregate(
                total_duration=Sum(
                    ExpressionWrapper(F('end_time') - F('start_time'), output_field=DurationField())
                )
            )
        )
        total_seconds = int(dur_agg['total_duration'].total_seconds()) if dur_agg['total_duration'] else 0
        discharge_rate = float(plot.zone.farm.discharge_rate or 0)
        context['stats'] = {
            'total_water': round(discharge_rate * total_seconds / 1000, 2),
            'avg_temperature': round(float(pw_stats['avg_temperature'] or 0), 1),
            'avg_wind_speed': round(float(pw_stats['avg_wind_speed'] or 0), 1),
            'avg_humidity': round(float(pw_stats['avg_humidity'] or 0), 1),
        }
        context['active_run_group'] = active_rg

        context['last_weather_check'] = PlotWeather.objects.filter(plot=plot).order_by('-created_at').first()

        context['outlets'] = plot.outlets.all()
        context['total_runs'] = Run.objects.filter(outlet__plot=plot).count()
        context['zones'] = Zone.objects.select_related('farm').all()
        latest_report = plot.ai_reports.order_by('-created_at').first()
        context['latest_report'] = latest_report

        health_scores = list(
            plot.ai_reports.order_by('-created_at')[:10].values_list('health_score', flat=True)
        )
        valid_scores = [s for s in health_scores if s is not None]
        context['avg_health_score'] = round(sum(valid_scores) / len(valid_scores)) if valid_scores else None

        from .gee import _ndvi_to_greenness, _ndmi_to_moisture
        ai_reports_qs = list(plot.ai_reports.order_by('-created_at')[:10])
        all_vis = list(PlotVegetationIndex.objects.filter(plot=plot).order_by('-id'))
        reports_with_vi = []
        for rpt in ai_reports_qs:
            vi = next((v for v in all_vis if v.created_at <= rpt.created_at), None) or (all_vis[0] if all_vis else None)
            ndvi_score = _ndvi_to_greenness(vi.ndvi) if vi and vi.ndvi is not None else None
            ndmi_score = _ndmi_to_moisture(vi.ndmi) if vi and vi.ndmi is not None else None
            reports_with_vi.append({
                'report': rpt, 'vi': vi,
                'ndvi_score': ndvi_score,
                'ndmi_score': ndmi_score,
            })
        context['reports_with_vi'] = reports_with_vi
        latest_vi = all_vis[0] if all_vis else None
        context['latest_vi'] = latest_vi
        context['ndvi_image_url'] = latest_vi.image.url if latest_vi and latest_vi.image else None
        context['ndmi_image_url'] = latest_vi.moisture_image.url if latest_vi and latest_vi.moisture_image else None
        context['satellite_image_url'] = latest_vi.satellite_image.url if latest_vi and latest_vi.satellite_image else None
        recent_vis = all_vis[:10]
        ndvi_vals = [float(v.ndvi) for v in recent_vis if v.ndvi is not None]
        ndmi_vals = [float(v.ndmi) for v in recent_vis if v.ndmi is not None]
        avg_ndvi = sum(ndvi_vals) / len(ndvi_vals) if ndvi_vals else None
        avg_ndmi = sum(ndmi_vals) / len(ndmi_vals) if ndmi_vals else None
        context['avg_ndvi'] = round(avg_ndvi, 3) if avg_ndvi is not None else None
        context['avg_ndmi'] = round(avg_ndmi, 3) if avg_ndmi is not None else None
        context['latest_greenness'] = _ndvi_to_greenness(avg_ndvi)
        context['latest_moisture'] = _ndmi_to_moisture(avg_ndmi)
        context['greenness_sample_count'] = len(ndvi_vals)
        context['moisture_sample_count'] = len(ndmi_vals)
        boundary = plot.boundary or []
        if boundary:
            lats = [p[0] for p in boundary if len(p) == 2]
            lngs = [p[1] for p in boundary if len(p) == 2]
            context['ndvi_bounds'] = [[min(lats), min(lngs)], [max(lats), max(lngs)]] if lats else None
        else:
            context['ndvi_bounds'] = None
        context['analyze_url'] = reverse('public:plot_condition_analyze', args=[plot.id])
        context['task_status_url'] = reverse('public:task_status', args=['TASK_ID'])
        context['weather_fetch_url'] = reverse('public:plot_weather_fetch', args=[plot.id])
        context['plot_weather_history'] = PlotWeather.objects.filter(plot=plot).order_by('-created_at')[:15]
        return context


class PlotCreateView(SuperVisorUserRequiredMixin, View):
    template_name = 'public/plot/form.html'

    def get(self, request):
        return render(request, self.template_name, {
            'form': forms.PlotForm(),
            'plot': None,
            'is_create': True,
        })

    def post(self, request):
        f = forms.PlotForm(request.POST)
        if f.is_valid():
            plot = f.save()
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True, 'id': plot.pk})
            messages.success(request, _('Plot created successfully'))
            return _redirect_with_next(request, reverse('public:plot_detail', args=[plot.pk]))
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'errors': f.errors})
        return render(request, self.template_name, {
            'form': f,
            'plot': None,
            'is_create': True,
        })


class PlotUpdateView(SuperVisorUserRequiredMixin, View):
    template_name = 'public/plot/form.html'

    def get(self, request, pk):
        plot = get_object_or_404(Plot, pk=pk)
        return render(request, self.template_name, {
            'form': forms.PlotForm(instance=plot),
            'plot': plot,
            'is_create': False,
        })

    def post(self, request, pk):
        plot = get_object_or_404(Plot, pk=pk)
        f = forms.PlotForm(request.POST, instance=plot)
        if f.is_valid():
            f.save()
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True})
            messages.success(request, _('Plot updated successfully'))
            return _redirect_with_next(request, reverse('public:plot_detail', args=[pk]))
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'errors': f.errors})
        return render(request, self.template_name, {
            'form': f,
            'plot': plot,
            'is_create': False,
        })


class PlotDeleteView(SuperVisorUserRequiredMixin, View):
    def post(self, request, pk):
        plot = get_object_or_404(Plot, pk=pk)
        plot.delete()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True})
        messages.success(request, _('Plot deleted successfully'))
        return redirect(reverse('public:plot_list'))


class PlotBoundaryUpdateView(SuperVisorUserRequiredMixin, View):
    def post(self, request, pk):
        plot = get_object_or_404(Plot, pk=pk)
        raw = request.POST.get('boundary') or '[]'
        try:
            data = json.loads(raw)
            if not isinstance(data, list):
                raise ValueError
            cleaned = []
            for p in data:
                if not isinstance(p, (list, tuple)) or len(p) != 2:
                    raise ValueError
                cleaned.append([float(p[0]), float(p[1])])
        except (ValueError, TypeError, json.JSONDecodeError):
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': str(_('Invalid boundary format'))}, status=400)
            messages.error(request, _('Invalid boundary format'))
            return redirect('public:plot_detail', pk=pk)
        plot.boundary = cleaned
        plot.save()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True})
        messages.success(request, _('Boundary updated successfully'))
        return redirect('public:plot_detail', pk=pk)


class PlotVegetationMapView(SuperVisorUserRequiredMixin, TemplateView):
    template_name = 'public/plot/vegetation_map.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        farm_id = self.request.GET.get('farm', '').strip()
        latest_ndvi = Subquery(
            PlotVegetationIndex.objects.filter(plot=OuterRef('pk'))
            .order_by('-observed_at').values('ndvi')[:1]
        )
        latest_ndmi = Subquery(
            PlotVegetationIndex.objects.filter(plot=OuterRef('pk'))
            .order_by('-observed_at').values('ndmi')[:1]
        )
        latest_ndre = Subquery(
            PlotVegetationIndex.objects.filter(plot=OuterRef('pk'))
            .order_by('-observed_at').values('ndre')[:1]
        )
        latest_evi = Subquery(
            PlotVegetationIndex.objects.filter(plot=OuterRef('pk'))
            .order_by('-observed_at').values('evi')[:1]
        )
        latest_savi = Subquery(
            PlotVegetationIndex.objects.filter(plot=OuterRef('pk'))
            .order_by('-observed_at').values('savi')[:1]
        )
        latest_msavi = Subquery(
            PlotVegetationIndex.objects.filter(plot=OuterRef('pk'))
            .order_by('-observed_at').values('msavi')[:1]
        )
        latest_at = Subquery(
            PlotVegetationIndex.objects.filter(plot=OuterRef('pk'))
            .order_by('-observed_at').values('observed_at')[:1]
        )
        latest_image = Subquery(
            PlotVegetationIndex.objects.filter(plot=OuterRef('pk'))
            .exclude(image='').exclude(image__isnull=True)
            .order_by('-observed_at').values('image')[:1]
        )
        latest_report_at = Subquery(
            PlotAIReport.objects.filter(plot=OuterRef('pk'))
            .order_by('-created_at').values('created_at')[:1]
        )
        latest_health = Subquery(
            PlotAIReport.objects.filter(plot=OuterRef('pk'))
            .order_by('-created_at').values('health_score')[:1]
        )
        qs = (
            Plot.objects.select_related('zone__farm')
            .annotate(
                latest_ndvi=latest_ndvi, latest_ndmi=latest_ndmi,
                latest_ndre=latest_ndre, latest_evi=latest_evi,
                latest_savi=latest_savi, latest_msavi=latest_msavi,
                latest_at=latest_at, latest_report_at=latest_report_at,
                latest_health=latest_health, latest_image=latest_image,
            )
        )
        if farm_id.isdigit():
            qs = qs.filter(zone__farm_id=farm_id)

        now = timezone.now()

        def _f(v):
            return float(v) if v is not None else None

        media_url = settings.MEDIA_URL

        plots_payload = []
        for p in qs:
            if not p.boundary and p.gps_lat is None:
                continue
            ndvi = float(p.latest_ndvi) if p.latest_ndvi is not None else None
            ndmi = float(p.latest_ndmi) if p.latest_ndmi is not None else None
            analysis_days = (now - p.latest_report_at).days if p.latest_report_at else None
            veg_image = f'{media_url}{p.latest_image}' if p.latest_image else None
            plots_payload.append({
                'id': p.id,
                'name': p.name,
                'zone': p.zone.name,
                'farm': p.zone.farm.name,
                'boundary': p.boundary or [],
                'center': [float(p.gps_lat), float(p.gps_lng)] if p.gps_lat is not None else None,
                'ndvi': ndvi,
                'ndmi': ndmi,
                'ndre': _f(p.latest_ndre),
                'evi': _f(p.latest_evi),
                'savi': _f(p.latest_savi),
                'msavi': _f(p.latest_msavi),
                'health': p.latest_health,
                'veg_image': veg_image,
                'observed_at': p.latest_at.isoformat() if p.latest_at else None,
                'analysis_days': analysis_days,
                'detail_url': reverse('public:plot_detail', args=[p.id]),
            })

        context['plots_json'] = json.dumps(plots_payload, ensure_ascii=False)
        context['farms'] = Farm.objects.all()
        context['farm_id'] = farm_id
        from .gee import (
            NDVI_SCORE_RANGES, NDMI_SCORE_RANGES,
            PISTACHIO_NDVI_PCT_MAX, PISTACHIO_NDMI_PCT_MIN, PISTACHIO_NDMI_PCT_MAX,
        )
        from django.utils.translation import gettext as _gettext
        ndvi_ranges = [{**v, 'label': _gettext(v['label'])} for v in NDVI_SCORE_RANGES.values()]
        ndmi_ranges = [{**v, 'label': _gettext(v['label'])} for v in NDMI_SCORE_RANGES.values()]
        context['ndvi_ranges_json'] = json.dumps(ndvi_ranges, ensure_ascii=False)
        context['ndmi_ranges_json'] = json.dumps(ndmi_ranges, ensure_ascii=False)
        context['pct_constants_json'] = json.dumps({
            'ndvi_max': PISTACHIO_NDVI_PCT_MAX,
            'ndmi_min': PISTACHIO_NDMI_PCT_MIN,
            'ndmi_max': PISTACHIO_NDMI_PCT_MAX,
        })
        return context


class PlotMoistureMapView(SuperVisorUserRequiredMixin, TemplateView):
    template_name = 'public/plot/moisture_map.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        farm_id = self.request.GET.get('farm', '').strip()
        latest_vi = PlotVegetationIndex.objects.filter(plot=OuterRef('pk')).order_by('-observed_at')
        latest_vi_with_moist = (
            PlotVegetationIndex.objects.filter(plot=OuterRef('pk'))
            .exclude(moisture_image='').exclude(moisture_image__isnull=True)
            .order_by('-observed_at')
        )
        qs = (
            Plot.objects.select_related('zone__farm')
            .annotate(
                latest_ndmi=Subquery(latest_vi.values('ndmi')[:1]),
                latest_ndvi=Subquery(latest_vi.values('ndvi')[:1]),
                latest_at=Subquery(latest_vi.values('observed_at')[:1]),
                latest_moisture_image=Subquery(latest_vi_with_moist.values('moisture_image')[:1]),
            )
        )
        if farm_id.isdigit():
            qs = qs.filter(zone__farm_id=farm_id)

        plots_payload = []
        for p in qs:
            if not p.boundary and p.gps_lat is None:
                continue
            ndmi = float(p.latest_ndmi) if p.latest_ndmi is not None else None
            ndvi = float(p.latest_ndvi) if p.latest_ndvi is not None else None
            moisture_url = ''
            if p.latest_moisture_image:
                moisture_url = settings.MEDIA_URL + p.latest_moisture_image
            plots_payload.append({
                'id': p.id,
                'name': p.name,
                'zone': p.zone.name,
                'farm': p.zone.farm.name,
                'boundary': p.boundary or [],
                'center': [float(p.gps_lat), float(p.gps_lng)] if p.gps_lat is not None else None,
                'ndmi': ndmi,
                'ndvi': ndvi,
                'observed_at': p.latest_at.isoformat() if p.latest_at else None,
                'detail_url': reverse('public:plot_detail', args=[p.id]),
                'moisture_image_url': moisture_url,
            })

        context['plots_json'] = json.dumps(plots_payload, ensure_ascii=False)
        context['farms'] = Farm.objects.all()
        context['farm_id'] = farm_id
        from .gee import (
            NDMI_SCORE_RANGES, NDVI_SCORE_RANGES,
            PISTACHIO_NDVI_PCT_MAX, PISTACHIO_NDMI_PCT_MIN, PISTACHIO_NDMI_PCT_MAX,
        )
        from django.utils.translation import gettext as _gettext
        ndmi_ranges = [{**v, 'label': _gettext(v['label'])} for v in NDMI_SCORE_RANGES.values()]
        ndvi_ranges = [{**v, 'label': _gettext(v['label'])} for v in NDVI_SCORE_RANGES.values()]
        context['ndmi_ranges_json'] = json.dumps(ndmi_ranges, ensure_ascii=False)
        context['ndvi_ranges_json'] = json.dumps(ndvi_ranges, ensure_ascii=False)
        context['pct_constants_json'] = json.dumps({
            'ndvi_max': PISTACHIO_NDVI_PCT_MAX,
            'ndmi_min': PISTACHIO_NDMI_PCT_MIN,
            'ndmi_max': PISTACHIO_NDMI_PCT_MAX,
        })
        return context


class PlotAnalyzeView(SuperVisorUserRequiredMixin, View):
    def post(self, request):
        from .tasks import analyze_all_plots
        plot_id = request.POST.get('plot', '').strip()
        farm_id = request.POST.get('farm', '').strip()
        if plot_id.isdigit():
            if not Plot.objects.filter(id=plot_id).exists():
                return JsonResponse({'success': False, 'error': str(_('Plot not found'))}, status=404)
            async_task('apps.public.tasks.analyze_plot', int(plot_id))
            return JsonResponse({'success': True, 'queued': 1})
        queued = analyze_all_plots(farm_id=int(farm_id) if farm_id.isdigit() else None)
        return JsonResponse({'success': True, 'queued': queued})


class SupervisorStopIrrigationView(SuperVisorUserRequiredMixin, View):
    def post(self, request, pk):
        group = get_object_or_404(models.RunGroup, pk=pk, status='running')
        group.plot.stop_run_group()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True})
        messages.success(request, _('Irrigation stopped successfully'))
        return redirect(reverse('public:index'))


LEAF_ENTITY_MODELS = {
    'farm': Farm,
    'zone': Zone,
    'plot': Plot,
    'outlet': Outlet,
}
LEAF_DETAIL_URLS = {
    'farm': 'public:farm_detail',
    'zone': 'public:zone__detail',
    'plot': 'public:plot_detail',
    'outlet': 'public:outlet_detail',
}


def _get_leaf_entity(entity, pk):
    model = LEAF_ENTITY_MODELS.get(entity)
    if model is None:
        raise Http404('Unknown leaf entity')
    return get_object_or_404(model, pk=pk)


def leaf_upload(request, pk, entity='plot'):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)
    obj = _get_leaf_entity(entity, pk)
    image = request.FILES.get('image')
    if not image:
        return JsonResponse({'success': False, 'error': str(_('No image provided'))})
    analysis = PlotLeafAnalysis.objects.create(image=image, status='analyzing', **{entity: obj})
    async_task('apps.public.tasks.analyze_leaf', analysis.pk)
    return JsonResponse({'success': True, 'queued': True, 'id': analysis.pk})


def leaf_list(request, pk, entity='plot'):
    obj = _get_leaf_entity(entity, pk)
    analyses = PlotLeafAnalysis.objects.filter(**{entity: obj}).order_by('-created_at')[:20]
    return render(request, 'public/plot/leaf_list.html', {
        'target': obj,
        'target_name': str(obj),
        'entity': entity,
        'analyses': analyses,
        'back_url': reverse(LEAF_DETAIL_URLS[entity], args=[obj.pk]),
    })


def plot_condition_analyze(request, pk):
    """Queue a rule-based plot analysis on django-q and return its task id for polling."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)
    plot = get_object_or_404(Plot, pk=pk)
    task_name = f'plot_analysis_{uuid.uuid4().hex[:12]}'
    task_id = async_task('apps.public.tasks.analyze_plot', plot.pk, task_name=task_name)
    return JsonResponse({'success': True, 'task_id': task_id, 'task_name': task_name})


def task_status(request, task_id):
    """Poll a django-q task; returns pending until the worker stores a result."""
    from django_q.tasks import fetch
    task = fetch(task_id)
    if task is None:
        return JsonResponse({'status': 'pending'})
    result = task.result if isinstance(task.result, dict) else None
    return JsonResponse({
        'status': 'done',
        'success': bool(task.success),
        'result': result,
    })


class PlotWeatherFetchView(SuperVisorUserRequiredMixin, View):
    """Queue an async weather fetch for a plot. Client polls task_status for the result."""

    def post(self, request, pk):
        plot = get_object_or_404(Plot, pk=pk)
        if not plot.gps_lat or not plot.gps_lng:
            return JsonResponse(
                {'success': False, 'error': str(_('No GPS coordinates set for this plot.'))},
                status=400,
            )
        task_id = async_task('apps.public.tasks.fetch_weather_for_plot', plot.pk, 'manual')
        return JsonResponse({'success': True, 'queued': True, 'task_id': task_id})




