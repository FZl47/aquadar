from django.urls import path

from . import views

app_name = 'ai_assistant'

urlpatterns = [
    path('experiment-analysis/', views.ExperimentAnalysisListView.as_view(), name='analysis_list'),
    path('experiment-analysis/create/', views.ExperimentAnalyzeView.as_view(), name='analyze'),
    path('experiment-analysis/<int:pk>/', views.ExperimentAnalysisDetailView.as_view(), name='analysis_detail'),
    path('experiment-analysis/<int:pk>/status/', views.ExperimentAnalysisStatusView.as_view(), name='analysis_status'),
    path('experiment-analysis/<int:pk>/delete/', views.ExperimentAnalysisDeleteView.as_view(), name='analysis_delete'),
    path('settings/', views.AISettingsView.as_view(), name='settings'),
]
