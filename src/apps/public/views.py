import json
import os
from decimal import Decimal
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse, JsonResponse
from django.views.generic import TemplateView, View, DetailView
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.contrib import messages
from django.urls import reverse_lazy, reverse
from django.db.models import (
    F, Case, When, DateTimeField, DurationField, Count, Avg, Q, Sum,
    Max, Min, OuterRef, Subquery, ExpressionWrapper, Prefetch, Exists
)
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.core.auth.mixins import WatermanUserRequiredMixin, SuperVisorUserRequiredMixin
from apps.core.forms.utils import form_validate_err

from . import models, forms
from .models import Farm, Zone, Plot, Outlet, Run, RunStatus, UserActivityReport, ReportManure, ManureCategory

User = get_user_model()


def get_general_stats():
    waterman_users = User.objects.filter(role='waterman')
    counts = Farm.objects.filter(is_active=True).aggregate(
        total_farms=Count('id'),
        total_zones=Count('zones', distinct=True),
        total_plots=Count('zones__plots', distinct=True),
        total_outlets=Count('zones__plots__outlets', distinct=True),
    )

    return {
        'waterman_users': waterman_users,
        'total_farms': counts['total_farms'] or 0,
        'total_zones': counts['total_zones'] or 0,
        'total_plots': counts['total_plots'] or 0,
        'total_outlets': counts['total_outlets'] or 0,
        'active_runs': Run.objects.filter(group__status='running').count(),
        'total_reports': UserActivityReport.objects.count(),
        'total_manure_reports': ReportManure.objects.count(),
    }


def get_runs_last_30_days():
    """نمودار Run‌ها در 30 روز گذشته"""
    thirty_days_ago = timezone.now() - timedelta(days=30)

    runs_by_date = Run.objects.filter(
        created_at__gte=thirty_days_ago
    ).annotate(
        date=TruncDate('created_at')
    ).values('date').annotate(
        count=Count('id')
    ).order_by('date')

    date_dict = {item['date']: item['count'] for item in runs_by_date}

    labels = []
    data = []

    for i in range(30):
        day = (timezone.now() - timedelta(days=29 - i)).date()
        labels.append(day.strftime('%m/%d'))
        data.append(date_dict.get(day, 0))

    return {
        'labels': labels,
        'data': data
    }


def get_run_status_distribution():
    counts = {
        item['group__status']: item['count']
        for item in Run.objects.values('group__status').annotate(count=Count('id'))
    }
    return {
        'labels': ['در حال آبیاری', 'تکمیل شده'],
        'data': [counts.get('running', 0), counts.get('completed', 0)],
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
            duration=ExpressionWrapper(
                F('end_time') - F('start_time'),
                output_field=DurationField()
            )
        )
        .values('outlet__plot__zone__name')
        .annotate(avg_dur=Avg('duration'))
        .filter(avg_dur__isnull=False)
        .order_by('outlet__plot__zone__name')
    )

    labels = []
    data = []
    for z in zone_data:
        labels.append(z['outlet__plot__zone__name'])
        data.append(round(z['avg_dur'].total_seconds() / 60, 2))

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
    """موقعیت‌های GPS ثبت شده"""
    locations = RunStatus.objects.filter(
        gps_lat__isnull=False,
        gps_lng__isnull=False
    ).select_related(
        'run__outlet__plot'
    ).values(
        'gps_lat',
        'gps_lng',
        'run__outlet__plot__name'
    )[:200]

    return [
        {
            'gps_lat': float(loc['gps_lat']),
            'gps_lng': float(loc['gps_lng']),
            'run__outlet__plot__name': loc.get('run__outlet__plot__name') or '',
        }
        for loc in locations
    ]


def get_manure_distribution():
    """توزیع کودها بر اساس دسته‌بندی"""

    data = (
        ReportManure.objects
        .values('category__title')
        .annotate(total=Count('id'))
        .order_by('-total')
    )

    labels = []
    values = []

    for item in data:
        labels.append(item['category__title'] or "Unknown")
        values.append(item['total'])

    return {
        "labels": labels,
        "data": values
    }


class Index(TemplateView):
    templates = {
        'waterman': 'public/dashboard/waterman.html',
        'supervisor': 'public/dashboard/supervisor.html'
    }

    def _resolve_role(self):
        role = self.request.user.role
        if role not in self.templates:
            role = 'supervisor' if self.request.user.is_superuser else 'waterman'
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
            'active_runnings': models.Run.objects.filter(created_by=user, group__status='running').exclude(
                runstatus__status='end'),
            'system_reports': models.SystemReport.objects.filter(to_users__in=[user]).exclude(
                systemreportstatus__status='resolved'),
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

        context = {
            **stats,
            "runs_labels": json.dumps(runs_chart["labels"]),
            "runs_data": json.dumps(runs_chart["data"]),
            "status_labels": json.dumps(status_chart["labels"]),
            "status_data": json.dumps(status_chart["data"]),
            "duration_labels": json.dumps(duration_chart["labels"]),
            "duration_data": json.dumps(duration_chart["data"]),
            "temp_labels": json.dumps(temp_chart["labels"]),
            "temp_data": json.dumps(temp_chart["data"]),
            "manure_labels": json.dumps(manure_chart["labels"]),
            "manure_data": json.dumps(manure_chart["data"]),
            "gps_locations": json.dumps(gps_locations),
            "run_settings": run_settings,
            "unresolved_system_reports": models.SystemReport.objects.select_related(
                'outlet__plot__zone__farm'
            ).exclude(systemreportstatus__status='resolved'),
        }
        return context


class PlotOutletActionByCode(WatermanUserRequiredMixin, View):

    def get_redirect_url(self):
        return self.request.META.get('HTTP_REFERER', reverse_lazy('public:index'))

    def get(self, request):
        """
            outlet_code => {farm-number}-{zone-number}-{outlet-number}
        """
        outlet_code = request.GET.get('outlet_code')
        if not outlet_code:
            messages.warning(request, _('Code number is empty'))
            return redirect(self.get_redirect_url())

        outlet_code_normalized = outlet_code.split('-')
        if len(outlet_code_normalized) != 3:
            messages.warning(request, _('Code number is invalid'))
            return redirect(self.get_redirect_url())

        farm_number = outlet_code_normalized[0]
        zone_number = outlet_code_normalized[1]
        outlet_number = outlet_code_normalized[2]

        user = request.user
        if user.is_superuser:
            outlet_obj = models.Outlet.objects.filter(plot__zone__farm__number=farm_number,
                                                      plot__zone__number=zone_number,
                                                      number=outlet_number)
        else:
            outlet_obj = models.Outlet.objects.filter(plot__zone__farm__number=farm_number,
                                                      plot__zone__number=zone_number,
                                                      number=outlet_number, plot__zone__farm__user__in=[user])
        if not outlet_obj.exists():
            messages.warning(request, _('Code number is wrong'))
            return redirect(self.get_redirect_url())

        outlet_obj = outlet_obj.first()

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
        run_group = plot.get_or_create_active_run_group()

        run_settings = models.RunSettings.objects.first()
        require_gps = run_settings.require_gps if run_settings else True

        if outlet_obj.status == 'not_started':
            if require_gps and (gps_lat is None or gps_lng is None):
                msg = str(_('Location (GPS) is required to start irrigation. Please enable location services.'))
                if is_ajax:
                    return JsonResponse({'success': False, 'message': msg})
                messages.error(request, msg)
                return redirect(self.get_redirect_url())
            run_obj = models.Run.objects.create(
                group=run_group, created_by=user, outlet=outlet_obj
            )
            models.RunStatus.objects.create(
                run=run_obj, status='start', gps_lat=gps_lat, gps_lng=gps_lng
            )
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
            run_obj = outlet_obj.status_start.run
            models.RunStatus.objects.create(
                run=run_obj, status='end', gps_lat=gps_lat, gps_lng=gps_lng
            )
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
            if all_done:
                messages.success(request, _('The run operation has completed'))
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

    def get(self, request, pk):
        report = get_object_or_404(models.SystemReport, pk=pk)
        statuses = report.get_statuses().select_related('user')

        # Check user have access to this report
        user = self.request.user
        if not user.is_superuser and not user.role == 'supervisor' and not report.to_users.filter(id=user.id).exists():
            raise Http404

        return render(request, self.template_name, {
            'report': report,
            'statuses': statuses
        })

    def post(self, request, pk):
        report = get_object_or_404(models.SystemReport, pk=pk)
        # Check user have access to this report
        user = self.request.user
        if not user.is_superuser and not user.role == 'supervisor' and not report.to_users.filter(id=user.id).exists():
            raise Http404

        data = request.POST.copy()
        data['user'] = user
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
        zone = self.object

        plots = zone.get_plots()
        outlets = Outlet.objects.filter(plot__zone=zone)

        # Stats
        context['plots_count'] = plots.count()
        context['outlets_count'] = outlets.count()

        # Irrigation runs
        runs = Run.objects.filter(outlet__plot__zone=zone)
        context['runs_count'] = runs.count()

        # Reports
        reports = models.SystemReport.objects.filter(outlet__plot__zone=zone)
        context['reports_count'] = reports.count()

        # Manure
        manure_reports = ReportManure.objects.filter(plot__zone=zone)
        context['manure_count'] = manure_reports.count()

        # Chart
        start_sub = RunStatus.objects.filter(
            run=OuterRef('pk'),
            status='start'
        ).values('created_at')[:1]

        end_sub = RunStatus.objects.filter(
            run=OuterRef('pk'),
            status='end'
        ).values('created_at')[:1]

        runs = (
            Run.objects.filter(outlet__plot__zone=zone)
            .annotate(
                start_time=Subquery(start_sub),
                end_time=Subquery(end_sub),
            )
            .exclude(start_time__isnull=True, end_time__isnull=True)
            .annotate(
                day=TruncDate('end_time'),
                duration=ExpressionWrapper(
                    F('end_time') - F('start_time'),
                    output_field=DurationField()
                )
            )
        )

        qs = (
            runs
            .exclude(end_time__isnull=True)
            .values('day')
            .annotate(total_duration=Sum('duration'))
            .order_by('day')
        )

        context['chart_labels'] = [
            x['day'].strftime('%Y-%m-%d') for x in qs
        ]

        context['chart_data'] = [
            round(x['total_duration'].total_seconds() / 60, 2)
            for x in qs
        ]

        return context



def get_plot_outlet_water_data(plot_id):
    plot = get_object_or_404(
        Plot.objects
        .select_related("zone__farm")
        .prefetch_related(
            Prefetch(
                "outlets__runs",
                queryset=Run.objects.filter(group__status='running').prefetch_related("runstatus_set")
            )
        ),
        id=plot_id
    )

    farm = plot.zone.farm
    discharge_rate = farm.discharge_rate or Decimal("0")

    outlet_rows = []

    total_plot_seconds = 0
    total_plot_liters = Decimal("0")

    for outlet in plot.outlets.all():

        total_seconds = 0
        run_count = 0

        for run in outlet.runs.all():

            duration = run.duration_seconds or 0

            if duration:
                total_seconds += duration
                run_count += 1

        total_liters = Decimal(total_seconds) * discharge_rate
        total_m3 = total_liters / Decimal("1000")

        total_plot_seconds += total_seconds
        total_plot_liters += total_liters
        outlet_rows.append({
            "outlet_id": outlet.id,
            "outlet_number": outlet.number,
            "run_count": run_count,
            "total_seconds": total_seconds,
            "total_minutes": round(total_seconds / 60, 2),
            "total_hours": round(total_seconds / 3600, 2),
            "total_liters": round(float(total_liters), 2),
            "total_m3": round(float(total_m3), 3),
            "status": outlet.status,
            "last_run_status_end": outlet.last_run_status_end,
            "status_label": outlet.status_label
        })

    outlet_rows.sort(key=lambda x: x["outlet_number"])

    return {
        "plot": plot,
        "farm": farm,
        "discharge_rate": float(discharge_rate),
        "outlets": outlet_rows,
        "total_plot_seconds": total_plot_seconds,
        "total_plot_hours": round(total_plot_seconds / 3600, 2),
        "total_plot_liters": round(float(total_plot_liters), 2),
        "total_plot_m3": round(float(total_plot_liters / Decimal("1000")), 3),
    }


def plot_outlet_discharge_view(request, plot_id):
    data = get_plot_outlet_water_data(plot_id)

    chart_labels = [f"Outlet {o['outlet_number']}" for o in data["outlets"]]
    chart_water = [o["total_m3"] for o in data["outlets"]]
    chart_duration = [o["total_hours"] for o in data["outlets"]]
    chart_runs = [o["run_count"] for o in data["outlets"]]

    context = {
        **data,
        "chart_labels": json.dumps(chart_labels),
        "chart_water": json.dumps(chart_water),
        "chart_duration": json.dumps(chart_duration),
        "chart_runs": json.dumps(chart_runs),
    }

    return render(request, "public/overview/plot_outlet_discharge.html", context)


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
        watermans = User.objects.filter(role='waterman')
        waterman_data = []
        for w in watermans:
            active_runs = list(
                models.Run.objects.filter(created_by=w, group__status='running')
                .select_related('outlet__plot__zone__farm')
            )
            last_weather = (
                models.RunStatus.objects.filter(run__created_by=w, weather_fetched=True)
                .select_related('run__outlet__plot__zone__farm')
                .order_by('-id').first()
            )
            if not last_weather:
                last_weather = (
                    models.RunStatus.objects.filter(run__created_by=w)
                    .select_related('run__outlet__plot__zone__farm')
                    .order_by('-id').first()
                )
            waterman_data.append({
                'user': w,
                'active_runs': active_runs,
                'active_runs_count': len(active_runs),
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


def service_worker_view(request):
    sw_path = os.path.join(settings.BASE_DIR, 'static', 'js', 'serviceworker.js')
    try:
        with open(sw_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        content = ''
    return HttpResponse(content, content_type='application/javascript')


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
                filter=Q(zones__plots__outlets__runs__group__status='running'),
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
            outlet__plot__zone__farm=farm, group__status='running'
        ).count()
        return context


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
                filter=Q(plots__outlets__runs__group__status='running'),
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


class OutletListView(SuperVisorUserRequiredMixin, TemplateView):
    template_name = 'public/outlet/list.html'
    PER_PAGE = 25

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        search = self.request.GET.get('q', '').strip()
        page_num = self.request.GET.get('page', 1)

        running_subq = Run.objects.filter(
            outlet=OuterRef('pk'),
            group__status='running',
        ).exclude(runstatus__status='end')

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
        outlet = self.object
        context['runs'] = (
            Run.objects.filter(outlet=outlet)
            .select_related('group', 'created_by')
            .prefetch_related('runstatus_set')
            .order_by('-id')[:20]
        )
        return context


class PlotDetailView(SuperVisorUserRequiredMixin, DetailView):
    model = Plot
    template_name = 'public/plot/detail.html'
    context_object_name = 'plot'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        plot = self.object

        rs_stats = RunStatus.objects.filter(run__outlet__plot=plot).aggregate(
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
        dur_agg = (
            Run.objects.filter(outlet__plot=plot)
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
            'avg_temperature': round(float(rs_stats['avg_temperature'] or 0), 1),
            'avg_wind_speed': round(float(rs_stats['avg_wind_speed'] or 0), 1),
            'avg_humidity': round(float(rs_stats['avg_humidity'] or 0), 1),
        }
        context['outlets'] = plot.outlets.all()
        context['total_runs'] = Run.objects.filter(outlet__plot=plot).count()
        return context


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
                filter=Q(outlets__runs__group__status='running'),
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


def offline_view(request):
    return render(request, 'public/offline.html')
