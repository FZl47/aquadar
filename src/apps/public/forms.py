from django import forms

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
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'عنوان گزارش'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'توضیحات...'}),
        }


class ReportManureForm(forms.ModelForm):
    class Meta:
        model = models.ReportManure
        fields = ['category', 'title', 'description']
        widgets = {
            'category': forms.Select(attrs={'class': 'form-control'}),
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'عنوان کوددهی'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'توضیحات...'}),
        }
