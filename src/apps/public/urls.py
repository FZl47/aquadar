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
    path('plot/<int:plot_id>/manure/create/', views.ReportManureCreateView.as_view(), name='report_manure__create'),
    path('watermans/', views.WatermanListView.as_view(), name='waterman_list'),
    path('runs/', views.RunListView.as_view(), name='run_list'),
    path('reports/manure/', views.ManureReportListView.as_view(), name='report_manure__list'),

    path('farms/', views.FarmListView.as_view(), name='farm_list'),
    path('farms/<int:pk>/', views.FarmDetailView.as_view(), name='farm_detail'),
    path('zones/', views.ZoneListView.as_view(), name='zone_list'),
    path('outlets/', views.OutletListView.as_view(), name='outlet_list'),
    path('outlets/<int:pk>/', views.OutletDetailView.as_view(), name='outlet_detail'),

    path('plots/', views.PlotListView.as_view(), name='plot_list'),
    path('plots/<int:pk>/', views.PlotDetailView.as_view(), name='plot_detail'),
    path('offline/', views.offline_view, name='offline'),
]
