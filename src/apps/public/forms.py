import os

import jdatetime

from django import forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from . import models


class SystemReportStatusForm(forms.ModelForm):
    class Meta:
        model = models.SystemReportStatus
        fields = '__all__'


class UserActivityReportForm(forms.ModelForm):
    class Meta:
        model = models.UserActivityReport
        fields = ['title', 'description']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        }


def _parse_jalali_date(value):
    """Parse Jalali date string YYYY/MM/DD → Gregorian date, or None if empty."""
    if value in (None, ''):
        return None
    try:
        return jdatetime.datetime.strptime(str(value).strip(), '%Y/%m/%d').togregorian().date()
    except (ValueError, AttributeError):
        raise forms.ValidationError(_('Invalid date. Use format: 1404/04/20'))


class RunSettingsForm(forms.ModelForm):

    class Meta:
        model = models.RunSettings
        fields = [
            'wind_speed_more_t', 'wind_speed_less_t', 'temp_value_more_t', 'temp_value_less_t',
            'expiration_run_time', 'avg_tolerance_run_duration', 'min_health_score',
            'create_report_to_supervisor_if_has_problem', 'require_gps', 'allow_code_entry',
        ]
        widgets = {
            'wind_speed_more_t': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'wind_speed_less_t': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'temp_value_more_t': forms.NumberInput(attrs={'class': 'form-control'}),
            'temp_value_less_t': forms.NumberInput(attrs={'class': 'form-control'}),
            'expiration_run_time': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'avg_tolerance_run_duration': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'min_health_score': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'max': 100}),
            'create_report_to_supervisor_if_has_problem': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'require_gps': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'allow_code_entry': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean_min_health_score(self):
        score = self.cleaned_data['min_health_score']
        if not 0 <= score <= 100:
            raise forms.ValidationError(_('Min health score must be between 0 and 100'))
        return score

    def clean_expiration_run_time(self):
        hours = self.cleaned_data['expiration_run_time']
        if hours < 1:
            raise forms.ValidationError(_('Expiration run time must be at least 1 hour'))
        return hours

    def clean_avg_tolerance_run_duration(self):
        minutes = self.cleaned_data['avg_tolerance_run_duration']
        if minutes < 0:
            raise forms.ValidationError(_('Tolerance cannot be negative'))
        return minutes

    def clean(self):
        cleaned = super().clean()
        wind_max, wind_min = cleaned.get('wind_speed_more_t'), cleaned.get('wind_speed_less_t')
        if wind_max is not None and wind_min is not None and wind_min > wind_max:
            self.add_error('wind_speed_less_t', _('Min wind speed cannot exceed max wind speed'))
        temp_max, temp_min = cleaned.get('temp_value_more_t'), cleaned.get('temp_value_less_t')
        if temp_max is not None and temp_min is not None and temp_min > temp_max:
            self.add_error('temp_value_less_t', _('Min temperature cannot exceed max temperature'))
        return cleaned


class FertilizationRecordForm(forms.ModelForm):
    """Waterman / compact form to register fertilization on a known plot."""
    due_date = forms.CharField(
        required=False,
        label=_('Due Date'),
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '1404/04/20',
            'dir': 'ltr',
        }),
    )

    class Meta:
        model = models.FertilizationRecord
        fields = ['category', 'title', 'quantity', 'unit', 'due_date', 'description']
        widgets = {
            'category': forms.Select(attrs={'class': 'form-control'}),
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001', 'min': '0'}),
            'unit': forms.Select(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def clean_due_date(self):
        return _parse_jalali_date(self.cleaned_data.get('due_date'))


def _plots_by_farm_map():
    """{farm_id: [{id, label}, ...]} for client-side farm→plot filtering."""
    data = {}
    qs = models.Plot.objects.select_related('zone__farm').order_by('zone__farm_id', 'name')
    for p in qs:
        farm_id = str(p.zone.farm_id)
        data.setdefault(farm_id, []).append({
            'id': p.pk,
            'label': f'{p.zone.name} / {p.name}',
        })
    return data


class FarmPlotFilterFormMixin:
    """Adds a convenience Farm filter that narrows the Plot queryset.

    Must be mixed into a Form/ModelForm; inserts ``farm`` into ``self.fields``
    during ``_setup_farm_plot_fields()`` (plain mixin attributes are not
    collected by Django's form metaclass).
    """

    def _setup_farm_plot_fields(self):
        plots = models.Plot.objects.select_related('zone__farm').order_by(
            'zone__farm__name', 'name'
        )

        farm_id = None
        if self.data.get('farm'):
            farm_id = self.data.get('farm')
        elif self.initial.get('farm'):
            farm_id = self.initial.get('farm')
        elif self.initial.get('plot'):
            try:
                plot = plots.filter(pk=self.initial['plot']).first()
                if plot:
                    farm_id = plot.zone.farm_id
                    self.initial.setdefault('farm', farm_id)
            except (TypeError, ValueError):
                pass
        elif self.data.get('plot'):
            try:
                plot = plots.filter(pk=self.data.get('plot')).first()
                if plot:
                    farm_id = plot.zone.farm_id
            except (TypeError, ValueError):
                pass

        self.fields['farm'] = forms.ModelChoiceField(
            queryset=models.Farm.objects.filter(is_active=True).order_by('name'),
            required=False,
            label=_('Farm'),
            widget=forms.Select(attrs={'class': 'form-control', 'id': 'id_farm'}),
            initial=farm_id if not self.data else None,
        )

        if farm_id:
            self.fields['plot'].queryset = plots.filter(zone__farm_id=farm_id)
            if not self.data:
                self.initial['farm'] = farm_id
        else:
            # No farm chosen yet — show all plots; JS filters on farm change.
            self.fields['plot'].queryset = plots

        self.fields['plot'].widget.attrs.update({'id': 'id_plot', 'class': 'form-control'})
        self.order_fields(['farm', 'plot'] + [
            name for name in self.fields if name not in ('farm', 'plot')
        ])

    def clean(self):
        cleaned = super().clean()
        farm = cleaned.get('farm')
        plot = cleaned.get('plot')
        if farm and plot and plot.zone.farm_id != farm.id:
            self.add_error('plot', _('Selected plot does not belong to the selected farm.'))
        return cleaned


class SupervisorFertilizationForm(FarmPlotFilterFormMixin, forms.ModelForm):
    """Supervisor form to register fertilization for any plot."""
    due_date = forms.CharField(
        required=False,
        label=_('Due Date'),
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '1404/04/20',
            'dir': 'ltr',
        }),
    )

    class Meta:
        model = models.FertilizationRecord
        fields = ['plot', 'category', 'title', 'quantity', 'unit', 'due_date', 'description']
        widgets = {
            'plot': forms.Select(attrs={'class': 'form-control', 'id': 'id_plot'}),
            'category': forms.Select(attrs={'class': 'form-control'}),
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001', 'min': '0'}),
            'unit': forms.Select(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._setup_farm_plot_fields()
        self.fields['category'].queryset = models.FertilizerCategory.objects.all()
        self.fields['category'].required = False
        # Show existing due_date as Jalali when editing.
        if self.instance and self.instance.pk and self.instance.due_date and not self.data:
            self.initial['due_date'] = jdatetime.date.fromgregorian(
                date=self.instance.due_date
            ).strftime('%Y/%m/%d')

    def clean_due_date(self):
        return _parse_jalali_date(self.cleaned_data.get('due_date'))


class FertilizerCategoryForm(forms.ModelForm):
    class Meta:
        model = models.FertilizerCategory
        fields = ['title', 'description']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }


class FoliarSprayCategoryForm(forms.ModelForm):
    class Meta:
        model = models.FoliarSprayCategory
        fields = ['title', 'description']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }


class ReportFoliarSprayForm(forms.ModelForm):
    due_date = forms.CharField(
        required=False,
        label=_('Due Date'),
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '1404/04/20',
            'dir': 'ltr',
        }),
    )

    class Meta:
        model = models.ReportFoliarSpray
        fields = ['category', 'title', 'quantity', 'unit', 'due_date', 'description']
        widgets = {
            'category': forms.Select(attrs={'class': 'form-control'}),
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001', 'min': '0'}),
            'unit': forms.Select(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def clean_due_date(self):
        return _parse_jalali_date(self.cleaned_data.get('due_date'))


class SupervisorFoliarSprayForm(FarmPlotFilterFormMixin, forms.ModelForm):
    """Supervisor form to register foliar spray for any plot."""
    due_date = forms.CharField(
        required=False,
        label=_('Due Date'),
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '1404/04/20',
            'dir': 'ltr',
        }),
    )

    class Meta:
        model = models.ReportFoliarSpray
        fields = ['plot', 'category', 'title', 'quantity', 'unit', 'due_date', 'description']
        widgets = {
            'plot': forms.Select(attrs={'class': 'form-control', 'id': 'id_plot'}),
            'category': forms.Select(attrs={'class': 'form-control'}),
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001', 'min': '0'}),
            'unit': forms.Select(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._setup_farm_plot_fields()
        self.fields['category'].queryset = models.FoliarSprayCategory.objects.all()
        self.fields['category'].required = False
        if self.instance and self.instance.pk and self.instance.due_date and not self.data:
            self.initial['due_date'] = jdatetime.date.fromgregorian(
                date=self.instance.due_date
            ).strftime('%Y/%m/%d')

    def clean_due_date(self):
        return _parse_jalali_date(self.cleaned_data.get('due_date'))


class FarmForm(forms.ModelForm):
    class Meta:
        model = models.Farm
        fields = ['number', 'name', 'pool_size', 'discharge_rate', 'is_active']
        widgets = {
            'number': forms.NumberInput(attrs={'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'pool_size': forms.NumberInput(attrs={'class': 'form-control'}),
            'discharge_rate': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class ZoneForm(forms.ModelForm):
    class Meta:
        model = models.Zone
        fields = ['number', 'name', 'farm', 'order']
        widgets = {
            'number': forms.NumberInput(attrs={'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'farm': forms.Select(attrs={'class': 'form-control'}),
            'order': forms.NumberInput(attrs={'class': 'form-control'}),
        }


class PlotForm(forms.ModelForm):
    boundary = forms.CharField(
        required=False,
        widget=forms.HiddenInput(attrs={'id': 'id_boundary'}),
        label=_('Boundary'),
    )

    class Meta:
        model = models.Plot
        fields = ['number', 'name', 'zone', 'avg_run_duration', 'boundary']
        widgets = {
            'number': forms.NumberInput(attrs={'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'zone': forms.Select(attrs={'class': 'form-control'}),
            'avg_run_duration': forms.NumberInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.boundary:
            import json as _json
            self.fields['boundary'].initial = _json.dumps(self.instance.boundary)

    def clean_boundary(self):
        import json as _json
        raw = self.cleaned_data.get('boundary') or ''
        if not raw:
            return []
        try:
            data = _json.loads(raw)
        except _json.JSONDecodeError:
            raise forms.ValidationError(_('Invalid boundary format'))
        if not isinstance(data, list):
            raise forms.ValidationError(_('Boundary must be a list of points'))
        cleaned = []
        for p in data:
            if not isinstance(p, (list, tuple)) or len(p) != 2:
                raise forms.ValidationError(_('Each point must be [lat, lng]'))
            try:
                cleaned.append([float(p[0]), float(p[1])])
            except (TypeError, ValueError):
                raise forms.ValidationError(_('Coordinates must be numbers'))
        return cleaned


class OutletForm(forms.ModelForm):
    class Meta:
        model = models.Outlet
        fields = ['number', 'plot']
        widgets = {
            'number': forms.NumberInput(attrs={'class': 'form-control'}),
            'plot': forms.Select(attrs={'class': 'form-control'}),
        }


class RunForm(forms.ModelForm):
    class Meta:
        model = models.Run
        fields = ['outlet', 'created_by', 'is_anomalous_short', 'is_anomalous_long']
        widgets = {
            'outlet': forms.Select(attrs={'class': 'form-control'}),
            'created_by': forms.Select(attrs={'class': 'form-control'}),
            'is_anomalous_short': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_anomalous_long': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class RunStatusForm(forms.ModelForm):
    class Meta:
        model = models.RunStatus
        fields = [
            'status', 'temperature_c', 'humidity', 'wind_speed', 'precipitation',
            'solar_radiation', 'uv_index', 'cloud_cover', 'gps_lat', 'gps_lng',
        ]
        widgets = {
            'status': forms.Select(attrs={'class': 'form-control'}),
            'temperature_c': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'humidity': forms.NumberInput(attrs={'class': 'form-control'}),
            'wind_speed': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'precipitation': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'solar_radiation': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'uv_index': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1'}),
            'cloud_cover': forms.NumberInput(attrs={'class': 'form-control'}),
            'gps_lat': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.000001'}),
            'gps_lng': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.000001'}),
        }


class ManualIrrigationForm(forms.Form):
    plot = forms.ModelChoiceField(
        queryset=models.Plot.objects.none(),
        label=_('Plot'),
        widget=forms.Select(attrs={'class': 'form-control', 'id': 'id_mi_plot'}),
    )
    outlets = forms.ModelMultipleChoiceField(
        queryset=models.Outlet.objects.none(),
        required=False,
        label=_('Outlets'),
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'mi-outlet-check', 'id': 'id_mi_outlets'}),
    )
    reporter = forms.ModelChoiceField(
        queryset=None,
        required=False,
        label=_('Reporter (Waterman)'),
        widget=forms.Select(attrs={'class': 'form-control'}),
    )
    start_jalali = forms.CharField(
        label=_('Start Date and Time (Jalali)'),
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '1404/04/20 08:30',
            'dir': 'ltr',
            'id': 'id_start_jalali',
        }),
    )
    end_jalali = forms.CharField(
        label=_('End Date and Time (Jalali)'),
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '1404/04/20 10:30',
            'dir': 'ltr',
            'id': 'id_end_jalali',
        }),
    )
    gps_lat = forms.DecimalField(
        required=False,
        max_digits=9,
        decimal_places=6,
        label=_('GPS Latitude'),
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.000001', 'id': 'id_mi_gps_lat'}),
    )
    gps_lng = forms.DecimalField(
        required=False,
        max_digits=9,
        decimal_places=6,
        label=_('GPS Longitude'),
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.000001', 'id': 'id_mi_gps_lng'}),
    )
    description = forms.CharField(
        required=False,
        label=_('Description'),
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
    )

    def __init__(self, *args, **kwargs):
        User = get_user_model()
        super().__init__(*args, **kwargs)
        self.fields['plot'].queryset = models.Plot.objects.select_related('zone__farm').all()
        self.fields['outlets'].queryset = models.Outlet.objects.select_related('plot__zone__farm').order_by(
            'plot_id', 'number'
        )
        self.fields['reporter'].queryset = User.objects.all()

    def _parse_jalali(self, value):
        try:
            return jdatetime.datetime.strptime(value.strip(), '%Y/%m/%d %H:%M').togregorian()
        except (ValueError, AttributeError):
            raise forms.ValidationError(_('Invalid date. Use format: 1404/04/20 08:30'))

    def clean_start_jalali(self):
        return self._parse_jalali(self.cleaned_data['start_jalali'])

    def clean_end_jalali(self):
        return self._parse_jalali(self.cleaned_data['end_jalali'])

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('start_jalali')
        end = cleaned.get('end_jalali')
        if start and end and end <= start:
            raise forms.ValidationError(_('End date must be after start date.'))
        plot = cleaned.get('plot')
        outlets = cleaned.get('outlets')
        if plot and outlets:
            invalid = [o for o in outlets if o.plot_id != plot.pk]
            if invalid:
                raise forms.ValidationError(_('Selected outlets must belong to the chosen plot.'))
        return cleaned


EXPERIMENT_ALLOWED_EXTENSIONS = (
    '.pdf', '.jpg', '.jpeg', '.png', '.webp', '.txt', '.csv', '.xls', '.xlsx', '.doc', '.docx',
)
EXPERIMENT_MAX_FILE_SIZE = 10 * 1024 * 1024


class ExperimentForm(forms.ModelForm):
    date = forms.CharField(
        label='تاریخ آزمایش',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '1404/04/20',
            'dir': 'ltr',
            'autocomplete': 'off',
            'data-jalali-datepicker': '1',
        }),
    )

    class Meta:
        model = models.Experiment
        fields = ['name', 'date', 'description', 'soil_file', 'leaf_file', 'water_file']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.date:
            self.initial['date'] = jdatetime.date.fromgregorian(date=self.instance.date).strftime('%Y/%m/%d')

    def clean_date(self):
        return _parse_jalali_date(self.cleaned_data.get('date'))

    def _clean_experiment_file(self, field_name):
        uploaded = self.cleaned_data.get(field_name)
        if uploaded and hasattr(uploaded, 'size') and not getattr(uploaded, '_committed', False):
            extension = os.path.splitext(uploaded.name)[1].lower()
            if extension not in EXPERIMENT_ALLOWED_EXTENSIONS:
                raise forms.ValidationError(
                    'فرمت فایل مجاز نیست. فرمت‌های مجاز: ' + ' '.join(EXPERIMENT_ALLOWED_EXTENSIONS)
                )
            if uploaded.size > EXPERIMENT_MAX_FILE_SIZE:
                raise forms.ValidationError('حجم فایل نباید بیشتر از ۱۰ مگابایت باشد.')
        return uploaded

    def clean_soil_file(self):
        return self._clean_experiment_file('soil_file')

    def clean_leaf_file(self):
        return self._clean_experiment_file('leaf_file')

    def clean_water_file(self):
        return self._clean_experiment_file('water_file')
