import logging
import os

from celery import shared_task
from django.urls import reverse_lazy
from django.utils import timezone

from apps.public.models import PlotLeafAnalysis
from apps.public.reports import create_system_report, resolve_recipients

from .reports import build_leaf_report
from .services import analyze_plot_leaf, run_experiment_analysis

logger = logging.getLogger(__name__)


@shared_task
def analyze_experiment(analysis_id):
    return run_experiment_analysis(analysis_id)


@shared_task
def analyze_leaf(analysis_id):
    """Run the AI leaf analysis for a pending PlotLeafAnalysis record."""
    try:
        analysis = PlotLeafAnalysis.objects.get(id=analysis_id)
    except PlotLeafAnalysis.DoesNotExist:
        return

    image_path = analysis.image.path if analysis.image else None
    if not image_path or not os.path.exists(image_path):
        PlotLeafAnalysis.objects.filter(pk=analysis_id).update(status='error')
        logger.error('Leaf image file missing for record %s', analysis_id)
        return

    result = analyze_plot_leaf(image_path)
    if not result:
        PlotLeafAnalysis.objects.filter(pk=analysis_id).update(status='error')
        logger.error('Leaf analysis failed for record %s', analysis_id)
        return

    PlotLeafAnalysis.objects.filter(pk=analysis_id).update(
        health_score=result.get('health_score'),
        diseases=result.get('diseases', []),
        deficiencies=result.get('deficiencies', []),
        pests=result.get('pests', []),
        recommendations=result.get('recommendations', []),
        prevention=result.get('prevention', []),
        urgency=result.get('urgency', ''),
        treatment_time=result.get('treatment_time', ''),
        summary=result.get('summary', ''),
        status='done',
        analyzed_at=timezone.now(),
    )
    _create_leaf_system_report(PlotLeafAnalysis.objects.get(pk=analysis_id))
    return analysis_id


def _create_leaf_system_report(analysis):
    target = analysis.target
    plot = analysis.plot or (analysis.outlet.plot if analysis.outlet_id else None)
    farm = analysis.farm
    if farm is None and analysis.zone_id:
        farm = analysis.zone.farm
    if farm is None and plot is not None:
        farm = plot.zone.farm
    recipients = resolve_recipients(farm)
    if not recipients:
        logger.warning('No recipients for leaf analysis %s report', analysis.pk)
        return None
    sections, priority = build_leaf_report(analysis)
    link = reverse_lazy(f'ai_assistant:{analysis.target_kind}_leaf_list', args=(target.pk,))
    system_report = create_system_report(
        category='leaf_analysis',
        title=f'گزارش تحلیل برگ {target}',
        summary=analysis.summary,
        sections=sections,
        priority=priority,
        recipients=recipients,
        subject=str(target),
        score=analysis.health_score,
        plot=plot,
        outlet=analysis.outlet,
        link=str(link),
    )
    PlotLeafAnalysis.objects.filter(pk=analysis.pk).update(final_report=system_report.final_report)
    return system_report
