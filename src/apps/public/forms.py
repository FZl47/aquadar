from django import forms
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
