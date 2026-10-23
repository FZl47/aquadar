import datetime
import os
import shutil
import tempfile
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.notification.models import NotificationConfig, NotificationUser

from .forms import ExperimentForm
from .models import (
    Experiment, Farm, FarmUserGroup, FertilizationRecord, ManualIrrigation, Outlet, Plot, Run, RunGroup, RunSettings, RunStatus, SystemReport,
    Zone,
)
from .reports import (
    create_system_report, format_final_report, item_text, make_section, plot_priority, resolve_recipients,
)
from .views import get_run_status_distribution

User = get_user_model()

TEMP_MEDIA_ROOT = tempfile.mkdtemp()


def make_hierarchy():
    farm = Farm.objects.create(number=1, name='باغ یک', discharge_rate=Decimal('10'))
    zone = Zone.objects.create(number=1, farm=farm, name='بخش یک')
    plot = Plot.objects.create(number=1, name='زمین یک', zone=zone, avg_run_duration=60)
    outlet = Outlet.objects.create(number=3, plot=plot)
    return farm, zone, plot, outlet


class ReportBuilderTests(SimpleTestCase):

    def test_item_text_dict_skips_empty(self):
        self.assertEqual(item_text({'name': 'اوره', 'dose': '5', 'timing': ''}), 'نام: اوره، مقدار: 5')

    def test_make_section_drops_empty_items(self):
        section = make_section('warnings', ['الف', '', None])
        self.assertEqual(section['items'], ['الف'])
        self.assertEqual(section['title'], 'هشدارها')

    def test_format_final_report_skips_empty_sections(self):
        text = format_final_report(
            'عنوان', summary='خلاصه',
            sections=[make_section('warnings', ['هشدار']), make_section('prevention', [])],
            priority='high', score=40,
        )
        self.assertIn('گزارش نهایی: عنوان', text)
        self.assertIn('اولویت: بالا', text)
        self.assertIn('امتیاز سلامت: 40 از 100', text)
        self.assertIn('1. هشدار', text)
        self.assertNotIn('پیشگیری', text)

    def test_plot_priority(self):
        self.assertEqual(plot_priority(30, [], 50), 'high')
        self.assertEqual(plot_priority(80, [{'severity': 'high'}], 50), 'high')
        self.assertEqual(plot_priority(60, [], 50), 'medium')
        self.assertEqual(plot_priority(95, [], 50), 'low')


class SystemReportPipelineTests(TestCase):

    def setUp(self):
        self.farm, self.zone, self.plot, self.outlet = make_hierarchy()
        self.sup = User.objects.create_user(username='sup', password='x', role='supervisor')
        self.other_sup = User.objects.create_user(username='sup2', password='x', role='supervisor')
        self.waterman = User.objects.create_user(username='wm', password='x', role='waterman')
        group = FarmUserGroup.objects.create(title='g', farm=self.farm)
        group.supervisors.add(self.sup)
        group.watermans.add(self.waterman)

    def test_resolve_recipients_farm_supervisors(self):
        users = resolve_recipients(self.farm)
        self.assertEqual([u.pk for u in users], [self.sup.pk])

    def test_resolve_recipients_fallback_to_all_supervisors(self):
        farm = Farm.objects.create(number=2, name='دو')
        pks = {u.pk for u in resolve_recipients(farm)}
        self.assertEqual(pks, {self.sup.pk, self.other_sup.pk})

    def test_resolve_recipients_dedups_extra(self):
        users = resolve_recipients(self.farm, extra=[self.sup, None, self.waterman])
        self.assertEqual(sorted(u.pk for u in users), sorted([self.sup.pk, self.waterman.pk]))

    def test_create_system_report_without_outlet(self):
        report = create_system_report(
            category='plot_analysis', title='تحلیل', summary='خلاصه',
            sections=[make_section('warnings', ['هشدار']), make_section('prevention', [])],
            priority='medium', recipients=[self.sup], plot=self.plot, link='/x/',
        )
        self.assertIsNone(report.outlet)
        self.assertEqual(report.farm, self.farm)
        self.assertEqual(report.category, 'plot_analysis')
        self.assertEqual(len(report.sections), 1)
        self.assertIn('گزارش نهایی: تحلیل', report.final_report)
        self.assertEqual(list(report.to_users.all()), [self.sup])
        notif = NotificationUser.objects.get(to_user=self.sup, type='system_report')
        self.assertEqual(notif.kwargs['priority_label'], 'متوسط')
        self.assertEqual(notif.kwargs['plot'], 'زمین یک')
        self.assertEqual(notif.kwargs['report_id'], report.pk)
        self.assertEqual(notif.description, report.final_report)

    def test_system_report_backfills_plot_from_outlet(self):
        report = SystemReport.objects.create(title='t', outlet=self.outlet, waterman=self.waterman)
        self.assertEqual(report.plot_id, self.plot.pk)

    def test_report_irrigation_bad_creates_report_and_notification(self):
        run = Run.objects.create(outlet=self.outlet, created_by=self.waterman)
        RunStatus.objects.create(run=run, status='start')
        report = run.report_irrigation_bad()
        self.assertIsNotNone(report)
        self.assertEqual(report.category, 'irrigation')
        self.assertEqual(report.plot_id, self.plot.pk)
        self.assertTrue(NotificationUser.objects.filter(to_user=self.sup, type='irrigation_issue_report').exists())


class OperationEventTests(TestCase):

    def setUp(self):
        self.farm, self.zone, self.plot, self.outlet = make_hierarchy()
        self.sup = User.objects.create_user(username='sup', password='x', role='supervisor')
        self.waterman = User.objects.create_user(username='wm', password='x', role='waterman')
        group = FarmUserGroup.objects.create(title='g', farm=self.farm)
        group.supervisors.add(self.sup)

    def test_fertilization_notifies_recipients_except_actor(self):
        FertilizationRecord.objects.create(plot=self.plot, title='اوره', created_by=self.sup)
        self.assertFalse(NotificationUser.objects.filter(to_user=self.sup).exists())
        FertilizationRecord.objects.create(plot=self.plot, title='پتاس', created_by=self.waterman)
        notif = NotificationUser.objects.get(to_user=self.sup)
        self.assertEqual(notif.type, 'operation_event')
        self.assertEqual(notif.kwargs['event'], 'fertilization_registered')
        self.assertEqual(notif.kwargs['plot'], 'زمین یک')

    def test_run_start_and_end_signals_notify_and_update_status(self):
        run = Run.objects.create(outlet=self.outlet, created_by=self.waterman)
        RunStatus.objects.create(run=run, status='start')
        run.refresh_from_db()
        self.assertEqual(run.status, 'open')
        self.assertTrue(NotificationUser.objects.filter(
            to_user=self.sup, kwargs__event='irrigation_started').exists())
        RunStatus.objects.create(run=run, status='end')
        run.refresh_from_db()
        self.assertEqual(run.status, 'closed')
        self.assertTrue(NotificationUser.objects.filter(
            to_user=self.sup, kwargs__event='irrigation_finished').exists())


class SystemReportDetailPageTests(TestCase):

    def setUp(self):
        self.farm, self.zone, self.plot, self.outlet = make_hierarchy()
        self.sup = User.objects.create_user(username='sup', password='pw12345!', role='supervisor')
        self.client.force_login(self.sup)

    def test_detail_renders_sections_and_priority(self):
        report = create_system_report(
            category='plot_analysis', title='تحلیل زمین', summary='وضعیت نیازمند توجه است',
            sections=[make_section('warnings', ['کمبود رطوبت']), make_section('recommendations', ['آبیاری عمیق'])],
            priority='high', recipients=[self.sup], plot=self.plot,
        )
        response = self.client.get(report.get_absolute_url())
        self.assertContains(response, 'sec-warnings')
        self.assertContains(response, 'کمبود رطوبت')
        self.assertContains(response, 'آبیاری عمیق')
        self.assertContains(response, 'prio-high')
        self.assertContains(response, 'وضعیت نیازمند توجه است')

    def test_detail_falls_back_to_final_report_without_sections(self):
        report = SystemReport.objects.create(
            title='قدیمی', plot=self.plot, final_report='متن گزارش نهایی قدیمی')
        response = self.client.get(report.get_absolute_url())
        self.assertContains(response, 'متن گزارش نهایی قدیمی')


class SupervisorDashboardTests(TestCase):

    def setUp(self):
        self.farm, self.zone, self.plot, self.outlet = make_hierarchy()
        self.sup = User.objects.create_user(username='dash', password='pw12345!', role='supervisor')
        self.client.force_login(self.sup)

    def test_unresolved_reports_ordered_by_priority(self):
        SystemReport.objects.create(title='low one', plot=self.plot, priority='low')
        SystemReport.objects.create(title='high one', plot=self.plot, priority='high')
        SystemReport.objects.create(title='medium one', plot=self.plot, priority='medium')
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        titles = [r.title for r in response.context['unresolved_system_reports']]
        self.assertEqual(titles, ['high one', 'medium one', 'low one'])
        self.assertEqual(response.context['unresolved_reports_total'], 3)
        self.assertEqual(response.context['unresolved_reports_high'], 1)

    def test_no_unresolved_reports(self):
        response = self.client.get('/')
        self.assertEqual(response.context['unresolved_reports_total'], 0)

    def test_report_row_has_age_badge_source(self):
        SystemReport.objects.create(title='aged one', plot=self.plot, priority='high')
        html = self.client.get('/').content.decode()
        self.assertIn('class="sr-age"', html)
        self.assertIn('data-created="', html)


class RunStatusDistributionTests(TestCase):

    def setUp(self):
        self.farm, self.zone, self.plot, self.outlet = make_hierarchy()

    def test_stale_running_group_without_open_run_is_not_counted_running(self):
        group = RunGroup.objects.create(plot=self.plot, status='running')
        Run.objects.create(group=group, outlet=self.outlet, status='closed')
        data = get_run_status_distribution()['data']
        self.assertEqual(data, [0, 1, 0])

    def test_open_run_counts_running_and_canceled_group_counts_canceled(self):
        group = RunGroup.objects.create(plot=self.plot, status='running')
        Run.objects.create(group=group, outlet=self.outlet, status='open')
        canceled = RunGroup.objects.create(plot=self.plot, status='canceled')
        Run.objects.create(group=canceled, outlet=self.outlet, status='closed')
        self.assertEqual(get_run_status_distribution()['data'], [1, 0, 1])


class IrrigationListPagesTests(TestCase):

    def setUp(self):
        self.farm, self.zone, self.plot, self.outlet = make_hierarchy()
        self.sup = User.objects.create_user(username='lst', password='pw12345!', role='supervisor')
        self.client.force_login(self.sup)

    def test_run_list_stats(self):
        group = RunGroup.objects.create(plot=self.plot, status='running')
        Run.objects.create(group=group, outlet=self.outlet, status='open')
        Run.objects.create(group=group, outlet=self.outlet, status='closed')
        response = self.client.get('/runs/')
        self.assertEqual(response.status_code, 200)
        stats = response.context['run_stats']
        self.assertEqual((stats['total'], stats['running'], stats['completed']), (2, 1, 1))

    def test_manual_list_totals(self):
        now = timezone.now()
        ManualIrrigation.objects.create(
            plot=self.plot, outlet=self.outlet, registered_by=self.sup,
            start_datetime=now, end_datetime=now, duration_seconds=3600)
        response = self.client.get('/manual-irrigation/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['manual_total_hours'], 1.0)
        self.assertEqual(response.context['manual_total_m3'], 36.0)


class SidebarGroupsTests(TestCase):

    def test_supervisor_sees_collapsible_groups(self):
        sup = User.objects.create_user(username='sbs', password='pw12345!', role='supervisor')
        self.client.force_login(sup)
        html = self.client.get('/').content.decode()
        for key in ('management', 'irrigations', 'reports', 'analysis'):
            self.assertIn('data-group="%s"' % key, html)
        self.assertIn('aq-group-toggle', html)

    def test_waterman_sees_limited_groups(self):
        wm = User.objects.create_user(username='sbw', password='pw12345!', role='waterman')
        self.client.force_login(wm)
        html = self.client.get('/').content.decode()
        self.assertIn('data-group="irrigations"', html)
        self.assertIn('data-group="reports"', html)
        self.assertNotIn('data-group="management"', html)


class ExperimentFormDatepickerTests(SimpleTestCase):

    def test_date_widget_uses_jalali_datepicker(self):
        self.assertIn('data-jalali-datepicker', str(ExperimentForm()['date']))


class SettingsPageSectionsTests(TestCase):

    def setUp(self):
        self.admin = User.objects.create_superuser(username='setadmin', password='pw12345!', role='supervisor')
        self.client.force_login(self.admin)
        self.valid = {
            'wind_speed_more_t': 30, 'wind_speed_less_t': 5, 'temp_value_more_t': 40, 'temp_value_less_t': 5,
            'expiration_run_time': 24, 'avg_tolerance_run_duration': 10, 'min_health_score': 50,
            'require_gps': 'on', 'allow_code_entry': 'on',
        }

    def test_page_lists_irrigation_and_notification_sections(self):
        html = self.client.get('/settings/').content.decode()
        self.assertIn('id="section-irrigation"', html)
        self.assertIn('id="section-notifications"', html)
        self.assertIn('id="section-ai"', html)

    def test_user_without_perms_forbidden(self):
        user = User.objects.create_user(username='setplain', password='pw12345!', role='waterman')
        self.client.force_login(user)
        self.assertEqual(self.client.get('/settings/').status_code, 403)

    def test_irrigation_post_creates_and_updates_settings(self):
        response = self.client.post('/settings/irrigation/', self.valid)
        self.assertRedirects(response, '/settings/#irrigation', fetch_redirect_response=False)
        run_settings = RunSettings.objects.get()
        self.assertEqual(run_settings.wind_speed_more_t, 30)
        self.assertFalse(run_settings.create_report_to_supervisor_if_has_problem)
        self.client.post('/settings/irrigation/', {**self.valid, 'wind_speed_more_t': 45})
        self.assertEqual(RunSettings.objects.count(), 1)
        self.assertEqual(RunSettings.objects.get().wind_speed_more_t, 45)

    def test_irrigation_rejects_min_above_max(self):
        self.client.post('/settings/irrigation/', {**self.valid, 'wind_speed_less_t': 99})
        self.assertFalse(RunSettings.objects.exists())

    def test_irrigation_rejects_bad_health_score(self):
        self.client.post('/settings/irrigation/', {**self.valid, 'min_health_score': 150})
        self.assertFalse(RunSettings.objects.exists())

    def test_notification_post_updates_config(self):
        response = self.client.post('/settings/notifications/', {'send_rubika_notify': 'on'})
        self.assertRedirects(response, '/settings/#notifications', fetch_redirect_response=False)
        config = NotificationConfig.objects.get()
        self.assertTrue(config.send_rubika_notify)
        self.assertFalse(config.send_sms_notify)

    def test_post_endpoints_reject_get(self):
        self.assertEqual(self.client.get('/settings/irrigation/').status_code, 405)
        self.assertEqual(self.client.get('/settings/notifications/').status_code, 405)


class WatermanDashboardPlotSelectTests(TestCase):

    def setUp(self):
        self.farm, self.zone, self.plot, self.outlet = make_hierarchy()
        other_farm = Farm.objects.create(number=2, name='باغ دو', discharge_rate=Decimal('5'))
        self.other_zone = Zone.objects.create(number=1, farm=other_farm, name='بخش بیگانه')
        Plot.objects.create(number=1, name='زمین بیگانه', zone=self.other_zone, avg_run_duration=60)
        self.wm = User.objects.create_user(username='wmsel', password='pw12345!', role='waterman')
        self.wm.farms.add(self.farm)
        self.client.force_login(self.wm)

    def test_only_user_farm_zones_and_plots_listed(self):
        response = self.client.get('/')
        self.assertEqual(list(response.context['zones']), [self.zone])
        self.assertEqual([p.name for p in response.context['plots']], ['زمین یک'])

    def test_zone_to_plot_markup_present(self):
        html = self.client.get('/').content.decode()
        self.assertIn('name="zone"', html)
        self.assertIn('zone="%s"' % self.zone.id, html)
        self.assertNotIn('بخش بیگانه', html)

    def test_plot_select_uses_jquery_change_handlers(self):
        html = self.client.get('/').content.decode()
        self.assertIn("$(zone_input).on('change'", html)
        self.assertIn("$(plot_input).on('change'", html)
        self.assertNotIn('zone_input.addEventListener', html)


class AdminUserFarmsTests(TestCase):

    def test_change_page_shows_farms_field(self):
        farm, zone, plot, outlet = make_hierarchy()
        admin_user = User.objects.create_superuser(username='adm', password='pw12345!', role='supervisor')
        target = User.objects.create_user(username='tgt', password='pw12345!', role='waterman')
        target.farms.add(farm)
        self.client.force_login(admin_user)
        html = self.client.get('/admin/account/user/%s/change/' % target.pk).content.decode()
        self.assertIn('name="farms"', html)
        changelist = self.client.get('/admin/account/user/').content.decode()
        self.assertIn(farm.name, changelist)


class PwaTests(TestCase):

    def test_manifest_public_and_installable(self):
        response = self.client.get('/manifest.json')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        sizes = {icon['sizes'] for icon in data['icons']}
        self.assertTrue({'192x192', '512x512'} <= sizes)
        self.assertEqual(data['display'], 'standalone')
        self.assertTrue(any(icon.get('purpose') == 'maskable' for icon in data['icons']))

    def test_service_worker_and_offline_public(self):
        sw = self.client.get('/serviceworker.js')
        self.assertEqual(sw.status_code, 200)
        self.assertIn('javascript', sw['Content-Type'])
        self.assertIn('/offline/', sw.content.decode())
        offline = self.client.get('/offline/')
        self.assertEqual(offline.status_code, 200)
        self.assertIn('اتصال اینترنت', offline.content.decode())

    def test_login_page_links_manifest(self):
        html = self.client.get(reverse('account:login')).content.decode()
        self.assertIn('rel="manifest"', html)


def _file(name='lab.pdf', content=b'%PDF-1.4 test'):
    return SimpleUploadedFile(name, content)


def _form_data():
    return {'name': 'آزمایش مرداد', 'date': '1404/05/10', 'description': 'نمونه'}


def _form_files():
    return {
        'soil_file': _file('soil.pdf'),
        'leaf_file': _file('leaf.pdf'),
        'water_file': _file('water.pdf'),
    }


def _grant(user, *codenames):
    user.user_permissions.add(*Permission.objects.filter(codename__in=codenames))


@override_settings(MEDIA_ROOT=TEMP_MEDIA_ROOT)
class ExperimentFormTests(TestCase):

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEMP_MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def test_valid_form_converts_jalali_date(self):
        form = ExperimentForm(_form_data(), _form_files())
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['date'], datetime.date(2025, 8, 1))

    def test_all_three_files_required(self):
        files = _form_files()
        files.pop('water_file')
        form = ExperimentForm(_form_data(), files)
        self.assertFalse(form.is_valid())
        self.assertIn('water_file', form.errors)

    def test_rejects_disallowed_extension(self):
        files = _form_files()
        files['soil_file'] = _file('soil.exe')
        form = ExperimentForm(_form_data(), files)
        self.assertFalse(form.is_valid())
        self.assertIn('soil_file', form.errors)

    def test_rejects_invalid_date(self):
        data = _form_data()
        data['date'] = 'not-a-date'
        form = ExperimentForm(data, _form_files())
        self.assertFalse(form.is_valid())
        self.assertIn('date', form.errors)

    def test_edit_without_new_files_keeps_existing(self):
        experiment = Experiment.objects.create(
            name='x', date=datetime.date(2025, 8, 1),
            soil_file=_file('soil.pdf'), leaf_file=_file('leaf.pdf'), water_file=_file('water.pdf'),
        )
        form = ExperimentForm(_form_data(), instance=experiment)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.initial['date'], '1404/05/10')


@override_settings(MEDIA_ROOT=TEMP_MEDIA_ROOT)
class ExperimentViewTests(TestCase):

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEMP_MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.user = User.objects.create_user(username='sup', password='pw12345!', role='supervisor')
        self.client.force_login(self.user)
        self.experiment = Experiment.objects.create(
            name='موجود', date=datetime.date(2025, 8, 1),
            soil_file=_file('soil.pdf'), leaf_file=_file('leaf.pdf'), water_file=_file('water.pdf'),
        )

    def test_list_forbidden_without_permission(self):
        response = self.client.get(reverse('public:experiment_list'))
        self.assertEqual(response.status_code, 403)

    def test_list_and_detail_with_view_permission(self):
        _grant(self.user, 'view_experiment')
        self.assertEqual(self.client.get(reverse('public:experiment_list')).status_code, 200)
        response = self.client.get(reverse('public:experiment_detail', args=[self.experiment.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'موجود')

    def test_create_requires_add_permission(self):
        _grant(self.user, 'view_experiment')
        response = self.client.post(reverse('public:experiment_create'), {**_form_data(), **_form_files()})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Experiment.objects.count(), 1)

    def test_create_with_permission_sets_creator(self):
        _grant(self.user, 'add_experiment', 'view_experiment')
        response = self.client.post(reverse('public:experiment_create'), {**_form_data(), **_form_files()})
        self.assertEqual(response.status_code, 302)
        created = Experiment.objects.exclude(pk=self.experiment.pk).get()
        self.assertEqual(created.created_by, self.user)
        self.assertEqual(created.date, datetime.date(2025, 8, 1))

    def test_update_requires_change_permission(self):
        url = reverse('public:experiment_update', args=[self.experiment.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        _grant(self.user, 'change_experiment', 'view_experiment')
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(url, _form_data())
        self.assertEqual(response.status_code, 302)
        self.experiment.refresh_from_db()
        self.assertEqual(self.experiment.name, 'آزمایش مرداد')

    def test_delete_requires_permission_and_removes_files(self):
        url = reverse('public:experiment_delete', args=[self.experiment.pk])
        self.assertEqual(self.client.post(url).status_code, 403)
        _grant(self.user, 'delete_experiment')
        stored_path = self.experiment.soil_file.path
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertFalse(Experiment.objects.filter(pk=self.experiment.pk).exists())
        with self.assertRaises(FileNotFoundError):
            open(stored_path, 'rb')

    def test_uploaded_files_get_random_names(self):
        stored = os.path.basename(self.experiment.soil_file.name)
        self.assertNotIn('soil', stored)
        self.assertTrue(stored.endswith('.pdf'))
        self.assertEqual(len(os.path.splitext(stored)[0]), 32)

    def test_bulk_delete_removes_files(self):
        paths = [getattr(self.experiment, field).path for field in Experiment.FILE_FIELDS]
        Experiment.objects.filter(pk=self.experiment.pk).delete()
        for path in paths:
            self.assertFalse(os.path.exists(path))

    def test_replacing_file_removes_old_one_after_save(self):
        old_path = self.experiment.soil_file.path
        self.experiment.soil_file = _file('new.pdf')
        self.experiment.save()
        self.assertFalse(os.path.exists(old_path))
        self.assertTrue(os.path.exists(self.experiment.soil_file.path))

    def test_superuser_has_full_access(self):
        admin = User.objects.create_superuser(username='root', password='pw12345!')
        self.client.force_login(admin)
        self.assertEqual(self.client.get(reverse('public:experiment_list')).status_code, 200)
        self.assertEqual(self.client.get(reverse('public:experiment_create')).status_code, 200)
