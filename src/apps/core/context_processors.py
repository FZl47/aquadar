def feature_flags(request):
    return {}


def sidebar_crud_options(request):
    """Lightweight farm/zone/plot options for the global sidebar CRUD modals."""
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {}
    if not (user.is_superuser or getattr(user, 'role', '') == 'supervisor'):
        return {}
    from apps.public.models import Farm, Zone, Plot
    return {
        'sidebar_farms': list(Farm.objects.values('pk', 'name')),
        'sidebar_zones': list(Zone.objects.select_related('farm').values('pk', 'name', 'farm__name')),
        'sidebar_plots': list(
            Plot.objects.select_related('zone__farm')
            .values('pk', 'name', 'zone__name', 'zone__farm__name')
        ),
    }
