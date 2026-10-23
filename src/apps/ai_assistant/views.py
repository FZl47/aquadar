from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import DeleteView, DetailView, FormView, ListView, UpdateView, View
from django_q.tasks import async_task

from apps.core.auth.mixins import PermissionMixin

from . import forms
from .models import AISettings, ExperimentAnalysis
from .providers.registry import get_provider, list_providers
from .services import get_main_provider_name


class ExperimentAnalyzeView(PermissionMixin, FormView):
    permissions = ('ai_assistant.add_experimentanalysis',)
    form_class = forms.ExperimentAnalyzeForm
    template_name = 'ai_assistant/analyze.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['main_provider'] = get_main_provider_name()
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        experiment_id = self.request.GET.get('experiment')
        if experiment_id and experiment_id.isdigit():
            initial['experiment'] = int(experiment_id)
        return initial

    def form_valid(self, form):
        provider_name = form.cleaned_data['provider_name']
        provider = get_provider(provider_name)
        analysis = ExperimentAnalysis.objects.create(
            experiment=form.cleaned_data['experiment'],
            requested_by=self.request.user,
            provider=provider_name,
            model_name=provider.model,
        )
        async_task('apps.ai_assistant.tasks.analyze_experiment', analysis.pk)
        messages.success(self.request, 'درخواست تحلیل ثبت شد و در حال پردازش است')
        return redirect('ai_assistant:analysis_detail', pk=analysis.pk)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['main_provider_name'] = get_main_provider_name()
        context['providers'] = list_providers()
        return context


class ExperimentAnalysisListView(PermissionMixin, ListView):
    permissions = ('ai_assistant.view_experimentanalysis',)
    template_name = 'ai_assistant/analysis_list.html'
    context_object_name = 'analyses'
    paginate_by = 20

    def get_queryset(self):
        return ExperimentAnalysis.objects.select_related('experiment', 'requested_by').order_by('-id')


class ExperimentAnalysisDetailView(PermissionMixin, DetailView):
    permissions = ('ai_assistant.view_experimentanalysis',)
    template_name = 'ai_assistant/analysis_detail.html'
    context_object_name = 'analysis'

    def get_queryset(self):
        return ExperimentAnalysis.objects.select_related('experiment', 'requested_by')


class ExperimentAnalysisStatusView(PermissionMixin, View):
    permissions = ('ai_assistant.view_experimentanalysis',)

    def get(self, request, pk):
        analysis = ExperimentAnalysis.objects.filter(pk=pk).only('status').first()
        if analysis is None:
            return JsonResponse({'status': 'missing', 'finished': True}, status=404)
        return JsonResponse({'status': analysis.status, 'finished': analysis.is_finished})


class ExperimentAnalysisDeleteView(PermissionMixin, DeleteView):
    permissions = ('ai_assistant.delete_experimentanalysis',)
    model = ExperimentAnalysis
    http_method_names = ['post']
    success_url = reverse_lazy('ai_assistant:analysis_list')

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, 'تحلیل حذف شد')
        return response


class AISettingsView(PermissionMixin, UpdateView):
    permissions = ('ai_assistant.change_aisettings',)
    form_class = forms.AISettingsForm
    template_name = 'ai_assistant/settings.html'
    success_url = reverse_lazy('ai_assistant:settings')

    def get_object(self, queryset=None):
        return AISettings.get_solo()

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, 'تنظیمات ذخیره شد')
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['providers'] = list_providers()
        context['effective_provider'] = get_main_provider_name()
        return context
