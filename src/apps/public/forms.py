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


class ReportManureForm(forms.ModelForm):
    class Meta:
        model = models.ReportManure
        fields = ['category', 'title', 'description']
        widgets = {
            'category': forms.Select(attrs={'class': 'form-control'}),
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


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
    outlet = forms.ModelChoiceField(
        queryset=models.Outlet.objects.none(),
        required=False,
        label=_('Outlet'),
        widget=forms.Select(attrs={'class': 'form-control', 'id': 'id_mi_outlet'}),
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
        self.fields['outlet'].queryset = models.Outlet.objects.select_related('plot__zone__farm').all()
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
        return cleaned
