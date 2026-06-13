from django import forms
from django.contrib import admin

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


@admin.register(models.Plot)
class PlotAdmin(admin.ModelAdmin):
    form = PlotAdminForm
    list_display = ("name", "zone", "farm_name")
    list_filter = ("zone__farm", "zone")
    search_fields = ("name", "zone__name", "zone__farm__name")
    inlines = [OutletInline]

    def farm_name(self, obj):
        return obj.zone.farm.name

    farm_name.short_description = "Farm"

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
    list_display = ('run', 'status', 'temperature_c', 'wind_speed', 'humidity', 'weather_fetched', 'gps_lat', 'gps_lng')
    list_filter = ('status', 'weather_fetched')
    date_hierarchy = 'created_at'


@admin.register(models.RunGroup)
class RunGroupAdmin(admin.ModelAdmin):
    list_display = ('plot', 'status', 'created_at')
    list_filter = ('status',)
    date_hierarchy = 'created_at'


@admin.register(models.RunSettings)
class RunSettingsAdmin(admin.ModelAdmin):
    list_display = ('expiration_run_time', 'avg_tolerance_run_duration', 'create_report_to_supervisor_if_has_problem', 'require_gps', 'allow_code_entry')


@admin.register(models.SystemReport)
class SystemReportAdmin(admin.ModelAdmin):
    list_display = ('title', 'waterman', 'outlet', 'priority', 'is_resolved', 'created_at')
    list_filter = ('priority',)
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

@admin.register(models.ReportManure)
class ReportManureAdmin(admin.ModelAdmin):
    list_display = ('title', 'created_by', 'category', 'plot', 'created_at')
    list_filter = ('category',)


@admin.register(models.ManureCategory)
class ManureCategoryAdmin(admin.ModelAdmin):
    list_display = ('title',)


@admin.register(models.FarmUserGroup)
class FarmUserGroupAdmin(admin.ModelAdmin):
    list_display = ('title', 'farm')
    filter_horizontal = ('watermans', 'supervisors')