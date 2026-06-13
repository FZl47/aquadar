from django.utils.translation import gettext_lazy as _
from django.shortcuts import redirect, render
from django.core.paginator import Paginator
from django.contrib import messages

from apps.core.forms.utils import form_validate_err


# TODO: refactor
# TODO: add docs/add type hints

class ViewMixin:
    pass


class CreateViewMixin(ViewMixin):
    validated_data = None
    obj = None
    form = None
    redirect_url = None

    def create(self, request, *args, **kwargs):
        data = request.POST.copy()
        # add request to form data
        self.data = data
        data['request'] = request

        try:
            additional_data = self.additional_data()
        except Exception as e:
            messages.error(request, str(e))
            return redirect(self.get_redirect_url())

        if additional_data:
            data.update(additional_data)
        form = self.get_form()(data=data, files=request.FILES)
        if not form_validate_err(request, form):
            return redirect(self.get_redirect_url())

        self.validated_data = form.cleaned_data
        self.before_save()
        self.obj = form.save()
        self.do_success()
        self.create_success_msg(request)
        return redirect(self.get_redirect_url())

    def get_redirect_url(self):
        return self.redirect_url or self.request.META.get('HTTP_REFERER', '/')

    def get_form(self):
        return self.form

    def additional_data(self):
        pass

    def before_save(self):
        pass

    def do_success(self):
        pass

    def create_success_msg(self, request):
        messages.success(request, _('The operation was successful.'))


class UpdateViewMixin(ViewMixin):
    validated_data = None
    obj = None
    instance = None
    form = None
    redirect_url = None

    def update(self, request, *args, **kwargs):
        data = request.POST.copy()
        # add request to form data
        self.data = data
        data['request'] = request
        instance = self.get_instance()
        self.instance = instance
        additional_data = self.additional_data()
        if additional_data:
            data.update(additional_data)
        form = self.get_form()(data=data, instance=instance)
        if not form_validate_err(request, form):
            return redirect(self.get_redirect_url())
        self.validated_data = form.cleaned_data
        self.obj = form.save()
        self.do_success()
        self.create_success_msg(request)
        return redirect(self.get_redirect_url())

    def get_redirect_url(self):
        return self.redirect_url or self.request.META.get('HTTP_REFERER', '/')

    def get_form(self):
        return self.form

    def get_instance(self):
        return None

    def additional_data(self):
        return None

    def do_success(self):
        pass

    def create_success_msg(self, request):
        messages.success(request, _('The operation was successful.'))


class ListViewMixin(ViewMixin):
    page_size = 20
    query_params = None
    form = None
    template_name = None

    def list(self, request, response=True, *args, **kwargs):
        form = self.get_form()
        if form:
            form = form(data=self.get_data_params())
            form.is_valid(raise_exception=True)
            self.query_params = form.validated_data
        else:
            self.query_params = self.get_data_params()
        query_set = self.get_queryset() or []
        paginator = Paginator(query_set, self.page_size)
        page = self.get_page(paginator)
        data = page.object_list
        context = {
            'pagination': page,
            'data': data,
            'data_count': len(data)
        }
        additional_context = self.additional_context()
        if additional_context:
            context.update(additional_context)
        return render(request, self.template_name, context)

    def get_form(self):
        return self.form

    def get_page(self, paginator):
        return paginator.get_page(self.query_params.get('page', 1))

    def get_queryset(self):
        return None

    def additional_context(self):
        return None

    def get_data_params(self):
        return self.request.GET


class CreateOrUpdateViewMixin(CreateViewMixin, UpdateViewMixin):
    pass


class FilterByDateViewMixin:
    query_params = None

    def filter(self, qs):
        query_params = self.query_params or {}

        fb_dc_start_from = query_params.get('fb_dc_start_from')
        fb_dc_end_to = query_params.get('fb_dc_end_to')

        if fb_dc_start_from:
            qs = qs.filter(created_at__gte=fb_dc_start_from)

        if fb_dc_end_to:
            qs = qs.filter(created_at__lte=fb_dc_end_to)

        return qs


class DetailViewMixin(ViewMixin):
    template_name = None
    obj = None

    def get(self, request, *args, **kwargs):
        self.obj = self.get_instance()

        context = {
            'object': self.obj
        }

        additional_context = self.additional_context()
        if additional_context:
            context.update(additional_context)

        return render(request, self.template_name, context)

    def get_instance(self):
        raise NotImplementedError

    def additional_context(self):
        return None


class DeleteViewMixin(ViewMixin):
    redirect_url = None
    obj = None

    def delete(self, request, kwargs):
        pk = kwargs['pk']
        self.obj = self.get_instance(pk)
        self.obj.delete()
        self.create_success_msg(request)

    def get(self, request, *args, **kwargs):
        self.delete(request, kwargs)
        return redirect(self.get_redirect_url())

    def get_redirect_url(self):
        return self.redirect_url

    def get_instance(self, pk):
        raise NotImplementedError

    def create_success_msg(self, request):
        messages.success(request, _('The operation was successful.'))
