from django.contrib import messages
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.translation import gettext as _
from django.views.generic import CreateView, DeleteView, DetailView, FormView, ListView, RedirectView, UpdateView, View

from apps.core.auth.mixins import PermissionMixin
from apps.public.models import Farm, Outlet, Plot, PlotLeafAnalysis, Zone

from . import forms
from .models import AIProviderConfig, AISettings, ExperimentAnalysis
from .providers.registry import BUILTIN_PROVIDER_NAMES, PROVIDER_CLASSES, get_provider, get_provider_labels, list_providers
from .services import get_main_provider_name
from .tasks import analyze_experiment, analyze_leaf


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
        analyze_experiment.delay(analysis.pk)
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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        labels = get_provider_labels()
        for analysis in context['analyses']:
            analysis.provider_labels = labels
        return context


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


class AISettingsView(PermissionMixin, RedirectView):
    permissions = ('ai_assistant.change_aisettings',)
    pattern_name = 'public:settings'


class AIMainProviderView(PermissionMixin, UpdateView):
    permissions = ('ai_assistant.change_aisettings',)
    form_class = forms.AISettingsForm
    http_method_names = ['post']
    success_url = reverse_lazy('public:settings')

    def get_object(self, queryset=None):
        return AISettings.get_solo()

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, 'ارائه‌دهنده اصلی ذخیره شد')
        return response

    def form_invalid(self, form):
        for errors in form.errors.values():
            for error in errors:
                messages.error(self.request, error)
        return redirect(self.success_url)


class AIProviderFormMixin(PermissionMixin):
    permissions = ('ai_assistant.change_aisettings',)
    model = AIProviderConfig
    form_class = forms.AIProviderConfigForm
    template_name = 'ai_assistant/provider_form.html'
    success_url = reverse_lazy('public:settings')

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, 'ارائه‌دهنده ذخیره شد')
        return response


class AIProviderCreateView(AIProviderFormMixin, CreateView):

    def get_initial(self):
        initial = super().get_initial()
        key = self.request.GET.get('key', '')
        if key in BUILTIN_PROVIDER_NAMES:
            initial.update({'key': key, 'provider_type': key, 'label': PROVIDER_CLASSES[key].label})
        return initial


class AIProviderUpdateView(AIProviderFormMixin, UpdateView):
    pass


class AIProviderDeleteView(PermissionMixin, DeleteView):
    permissions = ('ai_assistant.change_aisettings',)
    model = AIProviderConfig
    http_method_names = ['post']
    success_url = reverse_lazy('public:settings')

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, 'ارائه‌دهنده حذف شد')
        return response


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
    analyze_leaf.delay(analysis.pk)
    return JsonResponse({'success': True, 'queued': True, 'id': analysis.pk})


def leaf_list(request, pk, entity='plot'):
    obj = _get_leaf_entity(entity, pk)
    analyses = PlotLeafAnalysis.objects.filter(**{entity: obj}).order_by('-created_at')[:20]
    return render(request, 'ai_assistant/leaf_list.html', {
        'target': obj,
        'target_name': str(obj),
        'entity': entity,
        'analyses': analyses,
        'back_url': reverse(LEAF_DETAIL_URLS[entity], args=[obj.pk]),
    })
