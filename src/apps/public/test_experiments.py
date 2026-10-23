import datetime
import os
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .forms import ExperimentForm
from .models import Experiment

User = get_user_model()

TEMP_MEDIA_ROOT = tempfile.mkdtemp()


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
