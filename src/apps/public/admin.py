from django import forms
from django.contrib import admin
from django.utils.html import format_html

from . import models


class ZoneInline(admin.TabularInline):
    model = models.Zone
    extra = 0
    fields = ("name", "order")
    ordering = ("order",)


class PlotInline(admin.TabularInline):
    model = models.Plot
    extra = 1
    fields = ["name"]
    show_change_link = True


class OutletInline(admin.TabularInline):
    model = models.Outlet
    extra = 1


class PlotVegetationSoilReportInline(admin.TabularInline):
    model = models.PlotVegetationSoilReport
    extra = 0
    fields = ("label", "moisture_score", "greenness_score", "moisture_value", "greenness_value")


class RunStatusInline(admin.TabularInline):
    model = models.RunStatus
    extra = 1



@admin.register(models.Farm)
class FarmAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)
    inlines = [ZoneInline]


@admin.register(models.Zone)
class ZoneAdmin(admin.ModelAdmin):
    list_display = ("name", "farm", "order")
    list_editable = ("order",)
    ordering = ("farm", "order")
    inlines = [PlotInline]


class PlotAdminForm(forms.ModelForm):
    generate_outlets_count = forms.IntegerField(
        required=False,
        min_value=1,
        label="Generate outlets (1..n)",
        help_text="Enter a number to auto‑create outlets numbered 1 through n.(will delete all old objects)"
    )

    class Meta:
        model = models.Plot
        fields = "__all__"

    class Media:
        css = {'all': ['https://unpkg.com/leaflet@1.9.4/dist/leaflet.css']}
        js = ['https://unpkg.com/leaflet@1.9.4/dist/leaflet.js']


@admin.register(models.Plot)
class PlotAdmin(admin.ModelAdmin):
    form = PlotAdminForm
    list_display = ("name", "zone", "farm_name", "gps_lat", "gps_lng", "map_link", "ndvi_latest", "ndmi_latest")
    list_filter = ("zone__farm", "zone")
    search_fields = ("name", "zone__name", "zone__farm__name")
    readonly_fields = ('map_preview',)
    fieldsets = (
        (None, {'fields': ('name', 'number', 'zone', 'avg_run_duration', 'generate_outlets_count')}),
        ('موقعیت جغرافیایی', {'fields': ('gps_lat', 'gps_lng', 'map_preview')}),
    )
    inlines = [OutletInline, PlotVegetationSoilReportInline]

    def farm_name(self, obj):
        return obj.zone.farm.name
    farm_name.short_description = "Farm"

    def map_link(self, obj):
        if obj.gps_lat and obj.gps_lng:
            return format_html(
                '<a href="https://maps.google.com/?q={},{}" target="_blank">نقشه ↗</a>',
                obj.gps_lat, obj.gps_lng,
            )
        return '—'
    map_link.short_description = 'نقشه'

    def ndvi_latest(self, obj):
        vi = obj.vegetation_indices.order_by('-observed_at').first()
        if vi:
            return f'{vi.ndvi}'
        return '—'
    ndvi_latest.short_description = 'NDVI'

    def ndmi_latest(self, obj):
        vi = obj.vegetation_indices.order_by('-observed_at').first()
        if vi:
            return f'{vi.ndmi}'
        return '—'
    ndmi_latest.short_description = 'رطوبت (NDMI)'

    def map_preview(self, obj):
        if not obj.pk:
            return 'پس از ذخیره، نقشه نمایش داده می‌شود.'
        lat = float(obj.gps_lat) if obj.gps_lat else 32.0
        lng = float(obj.gps_lng) if obj.gps_lng else 53.0
        has_marker = 'true' if obj.gps_lat and obj.gps_lng else 'false'
        vi = obj.vegetation_indices.order_by('-observed_at').first()
        vi_info = f'NDVI: {vi.ndvi} | NDMI: {vi.ndmi} ({vi.observed_at})' if vi else 'داده‌ای موجود نیست'
        return format_html(
            '''
            <div>
              <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
              <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
              <div id="plot-map" style="height:320px;border-radius:10px;margin-bottom:8px;"></div>
              <div style="font-size:12px;color:#555;margin-bottom:8px;">📊 آخرین شاخص پوشش گیاهی: {}</div>
              <script>
                (function(){{
                  var map = L.map('plot-map').setView([{}, {}], 13);
                  L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{{z}}/{{y}}/{{x}}',
                    {{attribution:'© Esri', maxZoom:18}}).addTo(map);
                  var hasMarker = {};
                  var marker = null;
                  if (hasMarker) {{
                    marker = L.marker([{}, {}]).addTo(map);
                  }}
                  map.on('click', function(e) {{
                    var lat = e.latlng.lat.toFixed(6);
                    var lng = e.latlng.lng.toFixed(6);
                    document.getElementById('id_gps_lat').value = lat;
                    document.getElementById('id_gps_lng').value = lng;
                    if (marker) map.removeLayer(marker);
                    marker = L.marker([lat, lng]).addTo(map);
                  }});
                }})();
              </script>
            </div>
            ''',
            vi_info, lat, lng, has_marker, lat, lng,
        )
    map_preview.short_description = 'موقعیت روی نقشه'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('zone__farm').prefetch_related('vegetation_indices')

    def save_model(self, request, obj, form, change):
        # Save the plot itself first
        super().save_model(request, obj, form, change)

        # Check if user entered a number for auto‑generation
        n = form.cleaned_data.get("generate_outlets_count")
        if n:
            # Reset to exactly 1..n
            obj.outlets.all().delete()
            new_outlets = [models.Outlet(plot=obj, number=i) for i in range(1, n + 1)]
            models.Outlet.objects.bulk_create(new_outlets)



@admin.register(models.Outlet)
class OutletAdmin(admin.ModelAdmin):
    list_display = ("number", "plot", "zone_name", "farm_name")
    list_filter = ("plot__zone__farm", "plot__zone")
    search_fields = ("plot__name", "plot__zone__name", "plot__zone__farm__name")

    def zone_name(self, obj):
        return obj.plot.zone.name

    zone_name.short_description = "Zone"

    def farm_name(self, obj):
        return obj.plot.zone.farm.name

    farm_name.short_description = "Farm"


@admin.register(models.Run)
class RunAdmin(admin.ModelAdmin):
    inlines = [RunStatusInline]
    list_display = (
        "outlet",
        "plot_name",
        "zone_name",
        "farm_name",
        "duration_seconds",
        "is_anomalous_short",
        "is_anomalous_long",
    )
    list_filter = (
        "outlet__plot__zone__farm",
        "outlet__plot__zone",
        "outlet__plot",
        "is_anomalous_short",
        "is_anomalous_long",
    )
    search_fields = (
        "outlet__number",
        "outlet__plot__name",
        "outlet__plot__zone__name",
        "outlet__plot__zone__farm__name",
    )
    date_hierarchy = "created_at"

    def plot_name(self, obj):
        return obj.outlet.plot.name

    plot_name.short_description = "Plot"

    def zone_name(self, obj):
        return obj.outlet.plot.zone.name

    zone_name.short_description = "Zone"

    def farm_name(self, obj):
        return obj.outlet.plot.zone.farm.name

    farm_name.short_description = "Farm"


@admin.register(models.RunStatus)
class RunStatusAdmin(admin.ModelAdmin):
    list_display = ('run', 'status', 'temperature_c', 'wind_speed', 'humidity', 'precipitation', 'solar_radiation', 'uv_index', 'cloud_cover', 'weather_fetched', 'gps_lat', 'gps_lng')
    list_filter = ('status', 'weather_fetched')
    date_hierarchy = 'created_at'


@admin.register(models.RunGroup)
class RunGroupAdmin(admin.ModelAdmin):
    list_display = ('plot', 'status', 'created_at', 'stop_link')
    list_filter = ('status',)
    date_hierarchy = 'created_at'
    actions = ['cancel_irrigation']

    def stop_link(self, obj):
        if obj.status == 'running':
            url = f'/admin/public/rungroup/{obj.pk}/stop/'
            return format_html('<a href="{}" class="button" style="background:#e53935;color:#fff;padding:2px 10px;border-radius:6px;font-size:12px;">متوقف کردن</a>', url)
        return '—'
    stop_link.short_description = 'توقف آبیاری'

    def cancel_irrigation(self, request, queryset):
        count = 0
        for group in queryset.filter(status='running'):
            group.plot.stop_run_group()
            count += 1
        self.message_user(request, f'{count} آبیاری متوقف شد.')
    cancel_irrigation.short_description = 'متوقف کردن آبیاری‌های انتخاب شده'

    def get_urls(self):
        from django.urls import path as url_path
        urls = super().get_urls()
        custom = [url_path('<int:pk>/stop/', self.admin_site.admin_view(self.stop_view), name='rungroup_stop')]
        return custom + urls

    def stop_view(self, request, pk):
        from django.shortcuts import redirect
        try:
            group = models.RunGroup.objects.select_related('plot').get(pk=pk)
            if group.status == 'running':
                group.plot.stop_run_group()
                self.message_user(request, f'آبیاری زمین {group.plot} متوقف شد.')
        except models.RunGroup.DoesNotExist:
            self.message_user(request, 'گروه آبیاری یافت نشد.', level='error')
        return redirect('admin:public_rungroup_changelist')


@admin.register(models.RunSettings)
class RunSettingsAdmin(admin.ModelAdmin):
    list_display = (
        'expiration_run_time',
        'avg_tolerance_run_duration',
        'min_health_score',
        'create_report_to_supervisor_if_has_problem',
        'require_gps',
        'allow_code_entry',
    )


@admin.register(models.SystemReport)
class SystemReportAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'waterman', 'plot', 'outlet', 'priority', 'is_resolved', 'created_at')
    list_filter = ('priority', 'category')
    search_fields = ('title', 'description')
    date_hierarchy = 'created_at'


@admin.register(models.SystemReportStatus)
class SystemReportStatusAdmin(admin.ModelAdmin):
    list_display = ('report', 'user', 'status', 'created_at')
    list_filter = ('status',)


@admin.register(models.UserActivityReport)
class UserActivityReportAdmin(admin.ModelAdmin):
    list_display = ('title', 'created_by', 'created_at')
    search_fields = ('title',)


admin.site.register(models.UserActivityReportAttachFile)

@admin.register(models.FertilizationRecord)
class FertilizationRecordAdmin(admin.ModelAdmin):
    list_display = ('title', 'created_by', 'category', 'plot', 'quantity', 'unit', 'due_date', 'created_at')
    list_filter = ('category', 'unit', 'due_date')


@admin.register(models.FertilizerCategory)
class FertilizerCategoryAdmin(admin.ModelAdmin):
    list_display = ('title',)


@admin.register(models.FoliarSprayCategory)
class FoliarSprayCategoryAdmin(admin.ModelAdmin):
    list_display = ('title',)


@admin.register(models.ReportFoliarSpray)
class ReportFoliarSprayAdmin(admin.ModelAdmin):
    list_display = ('title', 'created_by', 'category', 'plot', 'quantity', 'unit', 'due_date', 'created_at')
    list_filter = ('category', 'unit', 'due_date')


@admin.register(models.FarmUserGroup)
class FarmUserGroupAdmin(admin.ModelAdmin):
    list_display = ('title', 'farm')
    filter_horizontal = ('watermans', 'supervisors')


@admin.register(models.PlotVegetationIndex)
class PlotVegetationIndexAdmin(admin.ModelAdmin):
    list_display = ['plot_link', 'ndvi', 'ndmi', 'source', 'observed_at', 'zone_name', 'farm_name', 'created_at']
    list_filter = ['source', 'plot__zone__farm', 'plot__zone']
    search_fields = ['plot__name', 'plot__zone__name', 'plot__zone__farm__name']
    date_hierarchy = 'observed_at'

    def plot_link(self, obj):
        url = f'/admin/public/plot/{obj.plot_id}/change/'
        return format_html('<a href="{}">{}</a>', url, obj.plot)
    plot_link.short_description = 'Plot'

    def zone_name(self, obj):
        return obj.plot.zone.name
    zone_name.short_description = 'Zone'

    def farm_name(self, obj):
        return obj.plot.zone.farm.name
    farm_name.short_description = 'Farm'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('plot__zone__farm')


@admin.register(models.PlotLeafAnalysis)
class PlotLeafAnalysisAdmin(admin.ModelAdmin):
    list_display = ['id', 'plot_link', 'zone_name', 'farm_name', 'health_score', 'status', 'urgency', 'analyzed_at', 'created_at']
    list_filter = ['status', 'urgency', 'plot__zone__farm', 'plot__zone']
    search_fields = ['plot__name', 'plot__zone__name', 'plot__zone__farm__name', 'summary']
    date_hierarchy = 'analyzed_at'
    readonly_fields = ['health_score', 'diseases', 'deficiencies', 'pests', 'recommendations', 'prevention', 'urgency', 'treatment_time', 'summary', 'status', 'analyzed_at']

    def plot_link(self, obj):
        url = f'/admin/public/plot/{obj.plot_id}/change/'
        return format_html('<a href="{}">{}</a>', url, obj.plot)
    plot_link.short_description = 'Plot'

    def zone_name(self, obj):
        return obj.plot.zone.name
    zone_name.short_description = 'Zone'

    def farm_name(self, obj):
        return obj.plot.zone.farm.name
    farm_name.short_description = 'Farm'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('plot__zone__farm')


@admin.register(models.PlotAIReport)
class PlotAIReportAdmin(admin.ModelAdmin):
    list_display = ['plot_link', 'zone_name', 'farm_name', 'health_score', 'created_at']
    list_filter = ['plot__zone__farm', 'plot__zone']
    search_fields = ['plot__name', 'plot__zone__name', 'plot__zone__farm__name', 'summary']
    date_hierarchy = 'created_at'

    def plot_link(self, obj):
        url = f'/admin/public/plot/{obj.plot_id}/change/'
        return format_html('<a href="{}">{}</a>', url, obj.plot)
    plot_link.short_description = 'Plot'

    def zone_name(self, obj):
        return obj.plot.zone.name
    zone_name.short_description = 'Zone'

    def farm_name(self, obj):
        return obj.plot.zone.farm.name
    farm_name.short_description = 'Farm'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('plot__zone__farm')


@admin.register(models.FarmAIReport)
class FarmAIReportAdmin(admin.ModelAdmin):
    list_display = ['farm', 'health_score', 'created_at']
    list_filter = ['farm']
    search_fields = ['farm__name', 'summary']
    date_hierarchy = 'created_at'


@admin.register(models.PlotVegetationSoilReport)
class PlotVegetationSoilReportAdmin(admin.ModelAdmin):
    list_display = ['plot_link', 'label', 'moisture_score', 'greenness_score', 'moisture_value', 'greenness_value', 'created_at']
    list_filter = ['plot__zone__farm', 'plot__zone']
    search_fields = ['plot__name', 'label', 'plot__zone__name', 'plot__zone__farm__name']
    date_hierarchy = 'created_at'

    def plot_link(self, obj):
        url = f'/admin/public/plot/{obj.plot_id}/change/'
        return format_html('<a href="{}">{}</a>', url, obj.plot)
    plot_link.short_description = 'Plot'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('plot__zone__farm')


@admin.register(models.Experiment)
class ExperimentAdmin(admin.ModelAdmin):
    list_display = ('name', 'date', 'created_by', 'created_at')
    list_filter = ('date',)
    search_fields = ('name', 'description')
    raw_id_fields = ('created_by',)
