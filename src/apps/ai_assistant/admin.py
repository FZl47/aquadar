from django.contrib import admin

from . import models


@admin.register(models.AISettings)
class AISettingsAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'main_provider', 'updated_at')

    def has_add_permission(self, request):
        return not models.AISettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(models.AIProviderConfig)
class AIProviderConfigAdmin(admin.ModelAdmin):
    list_display = ('key', 'label', 'provider_type', 'model', 'is_active')
    list_filter = ('provider_type', 'is_active')
    search_fields = ('key', 'label')


@admin.register(models.ExperimentAnalysis)
class ExperimentAnalysisAdmin(admin.ModelAdmin):
    list_display = ('experiment', 'provider', 'model_name', 'status', 'urgency', 'requested_by', 'created_at')
    list_filter = ('status', 'provider', 'urgency')
    search_fields = ('experiment__name', 'summary')
    raw_id_fields = ('experiment', 'requested_by')
    readonly_fields = ('result', 'raw_response', 'error_message', 'analyzed_at')
