from django.urls import path

from . import views

app_name = 'ai_assistant'

urlpatterns = [
    path('plots/<int:pk>/leaf/upload/', views.leaf_upload, {'entity': 'plot'}, name='plot_leaf_upload'),
    path('plots/<int:pk>/leaf/', views.leaf_list, {'entity': 'plot'}, name='plot_leaf_list'),
    path('farms/<int:pk>/leaf/upload/', views.leaf_upload, {'entity': 'farm'}, name='farm_leaf_upload'),
    path('farms/<int:pk>/leaf/', views.leaf_list, {'entity': 'farm'}, name='farm_leaf_list'),
    path('zones/<int:pk>/leaf/upload/', views.leaf_upload, {'entity': 'zone'}, name='zone_leaf_upload'),
    path('zones/<int:pk>/leaf/', views.leaf_list, {'entity': 'zone'}, name='zone_leaf_list'),
    path('outlets/<int:pk>/leaf/upload/', views.leaf_upload, {'entity': 'outlet'}, name='outlet_leaf_upload'),
    path('outlets/<int:pk>/leaf/', views.leaf_list, {'entity': 'outlet'}, name='outlet_leaf_list'),
    path('experiment-analysis/', views.ExperimentAnalysisListView.as_view(), name='analysis_list'),
    path('experiment-analysis/create/', views.ExperimentAnalyzeView.as_view(), name='analyze'),
    path('experiment-analysis/<int:pk>/', views.ExperimentAnalysisDetailView.as_view(), name='analysis_detail'),
    path('experiment-analysis/<int:pk>/status/', views.ExperimentAnalysisStatusView.as_view(), name='analysis_status'),
    path('experiment-analysis/<int:pk>/delete/', views.ExperimentAnalysisDeleteView.as_view(), name='analysis_delete'),
    path('settings/', views.AISettingsView.as_view(), name='settings'),
    path('settings/main-provider/', views.AIMainProviderView.as_view(), name='main_provider'),
    path('settings/providers/create/', views.AIProviderCreateView.as_view(), name='provider_create'),
    path('settings/providers/<int:pk>/update/', views.AIProviderUpdateView.as_view(), name='provider_update'),
    path('settings/providers/<int:pk>/delete/', views.AIProviderDeleteView.as_view(), name='provider_delete'),
]
