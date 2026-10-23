from django.urls import path

from . import views

app_name = 'public'

urlpatterns = [
    path('', views.Index.as_view(), name='index'),
    path('plot/outlet/<int:outlet_id>/action', views.PlotOutletAction.as_view(), name='plot_outlet_action'),
    path('plot/outlet/action/by-code', views.PlotOutletActionByCode.as_view(), name='plot_outlet_action_by_code'),
    path('plot/<int:plot_id>/outlets/run/reset', views.PlotOutletsRunReset.as_view(), name='plot_outlets_run_reset'),

    path('report/system/<int:pk>/detail', views.SystemReportDetail.as_view(), name='report_system__detail'),
    path('zone/<int:pk>/detail', views.ZoneDetail.as_view(), name='zone__detail'),
    path('plots/<int:plot_id>/outlets/', views.plot_outlet_discharge_view, name='plot_outlet_discharge'),

    path('reports/activity/', views.UserActivityReportListView.as_view(), name='report_activity__list'),
    path('reports/activity/create/', views.UserActivityReportCreateView.as_view(), name='report_activity__create'),
    path('plot/<int:plot_id>/fertilization/create/', views.WatermanFertilizationCreateView.as_view(), name='fertilization_waterman_create'),
    path('plot/<int:plot_id>/foliar-spray/create/', views.WatermanFoliarSprayCreateView.as_view(), name='report_foliar_spray__create'),
    path('watermans/', views.WatermanListView.as_view(), name='waterman_list'),

    path('runs/', views.RunListView.as_view(), name='run_list'),
    path('runs/<int:pk>/', views.RunDetailView.as_view(), name='run_detail'),
    path('runs/<int:pk>/update/', views.RunUpdateView.as_view(), name='run_update'),
    path('runs/<int:pk>/delete/', views.RunDeleteView.as_view(), name='run_delete'),
    path('run-status/<int:pk>/update/', views.RunStatusUpdateView.as_view(), name='runstatus_update'),
    path('run-status/<int:pk>/delete/', views.RunStatusDeleteView.as_view(), name='runstatus_delete'),

    path('reports/fertilization/', views.FertilizationListView.as_view(), name='fertilization_list'),
    path('reports/fertilization/create/', views.FertilizationCreateView.as_view(), name='fertilization_create'),
    path('reports/fertilization/<int:pk>/delete/', views.FertilizationDeleteView.as_view(), name='fertilization_delete'),
    path('reports/foliar-spray/', views.FoliarSprayListView.as_view(), name='foliar_spray_list'),
    path('reports/foliar-spray/create/', views.FoliarSprayCreateView.as_view(), name='foliar_spray_create'),
    path('reports/foliar-spray/<int:pk>/delete/', views.FoliarSprayDeleteView.as_view(), name='foliar_spray_delete'),
    path('categories/fertilizer/', views.FertilizerCategoryListView.as_view(), name='fertilizer_category_list'),
    path('categories/fertilizer/create/', views.FertilizerCategoryCreateView.as_view(), name='fertilizer_category_create'),
    path('categories/fertilizer/<int:pk>/delete/', views.FertilizerCategoryDeleteView.as_view(), name='fertilizer_category_delete'),
    path('categories/foliar-spray/', views.FoliarSprayCategoryListView.as_view(), name='foliar_spray_category_list'),
    path('categories/foliar-spray/create/', views.FoliarSprayCategoryCreateView.as_view(), name='foliar_spray_category_create'),
    path('categories/foliar-spray/<int:pk>/delete/', views.FoliarSprayCategoryDeleteView.as_view(), name='foliar_spray_category_delete'),

    path('farms/', views.FarmListView.as_view(), name='farm_list'),
    path('farms/create/', views.FarmCreateView.as_view(), name='farm_create'),
    path('farms/<int:pk>/', views.FarmDetailView.as_view(), name='farm_detail'),
    path('farms/<int:pk>/update/', views.FarmUpdateView.as_view(), name='farm_update'),
    path('farms/<int:pk>/discharge-rate/', views.FarmDischargeRateUpdateView.as_view(), name='farm_discharge_rate_update'),
    path('farms/<int:pk>/delete/', views.FarmDeleteView.as_view(), name='farm_delete'),


    path('zones/', views.ZoneListView.as_view(), name='zone_list'),
    path('zones/create/', views.ZoneCreateView.as_view(), name='zone_create'),
    path('zones/<int:pk>/update/', views.ZoneUpdateView.as_view(), name='zone_update'),
    path('zones/<int:pk>/delete/', views.ZoneDeleteView.as_view(), name='zone_delete'),

    path('outlets/', views.OutletListView.as_view(), name='outlet_list'),
    path('outlets/create/', views.OutletCreateView.as_view(), name='outlet_create'),
    path('outlets/<int:pk>/', views.OutletDetailView.as_view(), name='outlet_detail'),
    path('outlets/<int:pk>/update/', views.OutletUpdateView.as_view(), name='outlet_update'),
    path('outlets/<int:pk>/delete/', views.OutletDeleteView.as_view(), name='outlet_delete'),

    path('plots/map/vegetation/', views.PlotVegetationMapView.as_view(), name='plot_vegetation_map'),
    path('plots/map/moisture/', views.PlotMoistureMapView.as_view(), name='plot_moisture_map'),
    path('plots/analyze/', views.PlotAnalyzeView.as_view(), name='plot_analyze'),
    path('plots/', views.PlotListView.as_view(), name='plot_list'),
    path('plots/create/', views.PlotCreateView.as_view(), name='plot_create'),
    path('plots/<int:pk>/', views.PlotDetailView.as_view(), name='plot_detail'),
    path('plots/<int:pk>/update/', views.PlotUpdateView.as_view(), name='plot_update'),
    path('plots/<int:pk>/boundary/', views.PlotBoundaryUpdateView.as_view(), name='plot_boundary_update'),
    path('plots/<int:pk>/delete/', views.PlotDeleteView.as_view(), name='plot_delete'),
    path('plots/<int:pk>/leaf/upload/', views.leaf_upload, {'entity': 'plot'}, name='plot_leaf_upload'),
    path('plots/<int:pk>/leaf/', views.leaf_list, {'entity': 'plot'}, name='plot_leaf_list'),
    path('plots/<int:pk>/analyze/', views.plot_condition_analyze, name='plot_condition_analyze'),
    path('plots/<int:pk>/weather/fetch/', views.PlotWeatherFetchView.as_view(), name='plot_weather_fetch'),
    path('tasks/<str:task_id>/status/', views.task_status, name='task_status'),

    path('farms/<int:pk>/leaf/upload/', views.leaf_upload, {'entity': 'farm'}, name='farm_leaf_upload'),
    path('farms/<int:pk>/leaf/', views.leaf_list, {'entity': 'farm'}, name='farm_leaf_list'),
    path('zones/<int:pk>/leaf/upload/', views.leaf_upload, {'entity': 'zone'}, name='zone_leaf_upload'),
    path('zones/<int:pk>/leaf/', views.leaf_list, {'entity': 'zone'}, name='zone_leaf_list'),
    path('outlets/<int:pk>/leaf/upload/', views.leaf_upload, {'entity': 'outlet'}, name='outlet_leaf_upload'),
    path('outlets/<int:pk>/leaf/', views.leaf_list, {'entity': 'outlet'}, name='outlet_leaf_list'),

    path('irrigation/<int:pk>/stop/', views.SupervisorStopIrrigationView.as_view(), name='stop_irrigation'),

    path('manual-irrigation/', views.ManualIrrigationListView.as_view(), name='manual_irrigation_list'),
    path('manual-irrigation/create/', views.ManualIrrigationCreateView.as_view(), name='manual_irrigation_create'),
    path('manual-irrigation/<int:pk>/delete/', views.ManualIrrigationDeleteView.as_view(), name='manual_irrigation_delete'),

    path('experiments/', views.ExperimentListView.as_view(), name='experiment_list'),
    path('experiments/create/', views.ExperimentCreateView.as_view(), name='experiment_create'),
    path('experiments/<int:pk>/', views.ExperimentDetailView.as_view(), name='experiment_detail'),
    path('experiments/<int:pk>/update/', views.ExperimentUpdateView.as_view(), name='experiment_update'),
    path('experiments/<int:pk>/delete/', views.ExperimentDeleteView.as_view(), name='experiment_delete'),
]
