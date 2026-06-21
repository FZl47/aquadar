"""Sentinel-2 L2A vegetation indices via Microsoft Planetary Computer (STAC).

Free, key-less replacement for Google Earth Engine. Uses the public Planetary
Computer STAC API (collection ``sentinel-2-l2a``, 10 m), masks clouds with the
Scene Classification Layer (SCL) and computes NDVI / NDMI / NDRE / EVI / SAVI /
MSAVI over a plot polygon (or a buffered GPS point).

Public entry point::

    compute_vegetation_indices(plot, start_date=None, end_date=None,
                               cloud_cover_threshold=20)

``plot`` may be a Django ``Plot`` instance or a plain dict::

    {"gps_lat": float, "gps_lng": float, "boundary": [[lat, lng], ...]}

The module degrades gracefully: any missing dependency, missing geometry or empty
search returns ``{}`` instead of raising, so callers never crash.
"""
import datetime
import io
import logging
import math
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from django.db.models import (
    Case, DurationField, ExpressionWrapper, F, OuterRef, Subquery, Sum, When,
)
from django.db.models.functions import Now
from django.utils import timezone
from django.utils.translation import gettext as _

from .models import PlotVegetationIndex, Run, RunStatus

try:
    import numpy as _np
    _NUMPY_OK = True
except ImportError:
    _np = None
    _NUMPY_OK = False

try:
    from PIL import Image as _PilImage
    _PIL_OK = True
except ImportError:
    _PilImage = None
    _PIL_OK = False

# Pistachio (Pistacia vera) reference NDVI/NDMI ranges
PISTACHIO_NDVI_HEALTHY_MIN = 0.35  # NDVI ≥ 0.35 → healthy pistachio canopy
PISTACHIO_NDVI_STRESSED_MIN = 0.15 # NDVI 0.15-0.35 → moisture/nutrient stress
PISTACHIO_NDMI_ADEQUATE_MIN = 0.03 # NDMI ≥ 0.03 → adequate soil moisture
PISTACHIO_NDMI_STRESS_MIN = -0.12  # NDMI -0.12 to 0.03 → mild water stress

logger = logging.getLogger(__name__)

STAC_URL = 'https://planetarycomputer.microsoft.com/api/stac/v1'
COLLECTION = 'sentinel-2-l2a'
SOURCE = 'Sentinel-2 / Microsoft Planetary Computer'

# SCL classes to mask: 0 no-data, 1 saturated, 3 cloud shadow, 8 cloud medium,
# 9 cloud high, 10 thin cirrus, 11 snow/ice.
_SCL_BAD = (0, 1, 3, 8, 9, 10, 11)

# Planetary Computer Sentinel-2 L2A asset keys.
_BANDS = {
    'red': 'B04',
    'nir': 'B08',
    'swir': 'B11',
    'rededge': 'B05',
    'blue': 'B02',
    'scl': 'SCL',
}

_DEFAULT_DAYS_BACK = 60
_POINT_BUFFER_M = 50  # GPS fallback buffer (30-100 m range)
_TARGET_RES = 10.0    # metres


# Geometry helpers
def _plot_attr(plot, key):
    """Read a value from either a model instance or a dict."""
    if isinstance(plot, dict):
        return plot.get(key)
    return getattr(plot, key, None)


def _boundary_ring_lnglat(boundary):
    """Convert a [[lat, lng], ...] boundary to a closed [lng, lat] ring."""
    ring = []
    for p in boundary or []:
        try:
            if len(p) != 2:
                continue
            lat, lng = float(p[0]), float(p[1])
        except (TypeError, ValueError):
            continue
        ring.append([lng, lat])
    if len(ring) < 3:
        return None
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return ring


def _point_buffer_polygon(lat, lng, meters):
    """Build a small square polygon (lng, lat ring) around a GPS point."""
    dlat = meters / 111320.0
    dlng = meters / (111320.0 * max(math.cos(math.radians(lat)), 1e-6))
    return [
        [lng - dlng, lat - dlat],
        [lng + dlng, lat - dlat],
        [lng + dlng, lat + dlat],
        [lng - dlng, lat + dlat],
        [lng - dlng, lat - dlat],
    ]


def _resolve_geometry(plot):
    """Return (geojson_geometry, geometry_type) in EPSG:4326 lng/lat, or (None, None)."""
    ring = _boundary_ring_lnglat(_plot_attr(plot, 'boundary'))
    if ring is not None:
        return {'type': 'Polygon', 'coordinates': [ring]}, 'polygon'

    lat = _plot_attr(plot, 'gps_lat')
    lng = _plot_attr(plot, 'gps_lng')
    if lat is not None and lng is not None:
        try:
            ring = _point_buffer_polygon(float(lat), float(lng), _POINT_BUFFER_M)
        except (TypeError, ValueError):
            return None, None
        return {'type': 'Polygon', 'coordinates': [ring]}, 'buffered_point'

    return None, None


def _geom_bounds(geometry):
    coords = geometry['coordinates'][0]
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    return min(xs), min(ys), max(xs), max(ys)


# STAC search — module-level catalog singleton (avoids re-opening on every call)
_stac_catalog = None


def _get_stac_catalog():
    global _stac_catalog
    if _stac_catalog is None:
        try:
            import planetary_computer
            import pystac_client
        except ImportError:
            logger.error('pystac-client / planetary-computer not installed')
            return None
        try:
            _stac_catalog = pystac_client.Client.open(
                STAC_URL, modifier=planetary_computer.sign_inplace,
            )
        except Exception as exc:
            logger.error('STAC catalog open failed: %s', exc)
            return None
    return _stac_catalog


def _search_items(geometry, start_date, end_date, cloud_cover_threshold):
    """Return STAC items sorted by ascending cloud cover, or [] when unavailable."""
    catalog = _get_stac_catalog()
    if catalog is None:
        return []

    date_range = f'{start_date.isoformat()}/{end_date.isoformat()}'

    def _run(threshold):
        try:
            search = catalog.search(
                collections=[COLLECTION],
                intersects=geometry,
                datetime=date_range,
                query={'eo:cloud_cover': {'lt': threshold}},
            )
            return list(search.items())
        except Exception as exc:
            logger.error('STAC search failed: %s', exc)
            return []

    items = _run(cloud_cover_threshold)
    if not items:
        # Retry once with a relaxed cloud threshold before giving up.
        items = _run(min(cloud_cover_threshold + 40, 100))
    items.sort(key=lambda it: it.properties.get('eo:cloud_cover', 100))
    return items


# Raster reading
def _utm_epsg(lng, lat):
    zone = int((lng + 180) / 6) + 1
    return (32600 if lat >= 0 else 32700) + zone


def _read_band(href, target_crs, transform, width, height, resampling):
    import rasterio
    from rasterio.vrt import WarpedVRT
    with rasterio.open(href) as src:
        with WarpedVRT(
            src, crs=target_crs, transform=transform,
            width=width, height=height, resampling=resampling,
        ) as vrt:
            return vrt.read(1)


def _read_stack(item, geometry):
    """Read all bands onto a common 10 m UTM grid clipped to the AOI.

    Returns (bands_dict, aoi_mask) or (None, None) on failure.
    """
    if not _NUMPY_OK:
        logger.error('numpy not installed')
        return None, None
    np = _np
    try:
        from rasterio.enums import Resampling
        from rasterio.features import geometry_mask
        from rasterio.transform import from_origin
        from rasterio.warp import transform_bounds, transform_geom
    except ImportError:
        logger.error('rasterio not installed')
        return None, None

    minx, miny, maxx, maxy = _geom_bounds(geometry)
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    epsg = item.properties.get('proj:epsg') or _utm_epsg(cx, cy)
    target_crs = f'EPSG:{epsg}'

    try:
        bx0, by0, bx1, by1 = transform_bounds('EPSG:4326', target_crs, minx, miny, maxx, maxy)
    except Exception as exc:
        logger.error('AOI reprojection failed: %s', exc)
        return None, None

    width = max(int(math.ceil((bx1 - bx0) / _TARGET_RES)), 1)
    height = max(int(math.ceil((by1 - by0) / _TARGET_RES)), 1)
    transform = from_origin(bx0, by1, _TARGET_RES, _TARGET_RES)

    assets = item.assets
    for name, key in _BANDS.items():
        if assets.get(key) is None:
            logger.warning('Item %s missing asset %s', item.id, key)
            return None, None

    def _fetch_band(name, key):
        resampling = Resampling.nearest if name == 'scl' else Resampling.bilinear
        arr = _read_band(assets[key].href, target_crs, transform, width, height, resampling)
        return name, arr.astype('float32')

    bands = {}
    try:
        with ThreadPoolExecutor(max_workers=len(_BANDS)) as pool:
            futs = {pool.submit(_fetch_band, n, k): n for n, k in _BANDS.items()}
            for fut in as_completed(futs):
                n, arr = fut.result()
                bands[n] = arr
    except Exception as exc:
        logger.error('Band read failed for item %s: %s', item.id, exc)
        return None, None

    try:
        geom_utm = transform_geom('EPSG:4326', target_crs, geometry)
        aoi_mask = geometry_mask(
            [geom_utm], out_shape=(height, width), transform=transform, invert=True,
        )
    except Exception as exc:
        logger.error('AOI mask build failed: %s', exc)
        return None, None

    return bands, aoi_mask


# Index computation
def _compute_indices(bands, valid):
    import numpy as np

    scale = 1.0 / 10000.0
    nir = bands['nir'] * scale
    red = bands['red'] * scale
    swir = bands['swir'] * scale
    rededge = bands['rededge'] * scale
    blue = bands['blue'] * scale

    with np.errstate(divide='ignore', invalid='ignore'):
        ndvi = (nir - red) / (nir + red)
        ndmi = (nir - swir) / (nir + swir)
        ndre = (nir - rededge) / (nir + rededge)
        evi = 2.5 * (nir - red) / (nir + 6.0 * red - 7.5 * blue + 1.0)
        savi = 1.5 * (nir - red) / (nir + red + 0.5)
        msavi = (2 * nir + 1 - np.sqrt((2 * nir + 1) ** 2 - 8 * (nir - red))) / 2

    out = {}
    indices = {'ndvi': ndvi, 'ndmi': ndmi, 'ndre': ndre, 'evi': evi, 'savi': savi, 'msavi': msavi}
    for name, arr in indices.items():
        masked = np.where(valid, arr, np.nan)
        finite = masked[np.isfinite(masked)]
        if finite.size == 0:
            out[name] = {'mean': None, 'min': None, 'max': None}
        else:
            out[name] = {
                'mean': round(float(np.mean(finite)), 4),
                'min': round(float(np.min(finite)), 4),
                'max': round(float(np.max(finite)), 4),
            }
    out['_ndvi_array'] = np.where(valid, ndvi, np.nan)
    return out


# NDVI colour ramp matching the map legend (very-poor red -> excellent green).
# Extended NDVI colour ramp: water (blue) → bare (gray) → sparse (red) → dense (dark green)
_NDVI_RAMP = (
    (-0.05, (33,  150, 243)),   # water / snow
    (0.10,  (158, 158, 158)),   # bare soil / urban
    (0.20,  (211,  47,  47)),   # very sparse vegetation
    (0.35,  (239, 108,   0)),   # sparse
    (0.50,  (251, 192,  45)),   # moderate
    (0.65,  (124, 179,  66)),   # good canopy
    (10.0,  (27,   94,  32)),   # dense / healthy
)
_NDVI_PNG_MAX_DIM = 768


def _ndvi_png(ndvi_array):
    """Render an NDVI array to a coloured PNG (bytes) for the vegetation thumbnail."""
    if not _NUMPY_OK or not _PIL_OK:
        return None
    np = _np
    Image = _PilImage
    try:
        h, w = ndvi_array.shape
        rgb = np.zeros((h, w, 3), dtype='uint8')
        alpha = np.zeros((h, w), dtype='uint8')

        # No-data pixels: light gray at 50% opacity so background shows through
        nan_mask = ~np.isfinite(ndvi_array)
        rgb[nan_mask] = (200, 200, 200)
        alpha[nan_mask] = 128

        for thresh, color in _NDVI_RAMP:
            sel = np.isfinite(ndvi_array) & (ndvi_array < thresh) & (alpha == 0)
            rgb[sel] = color
            alpha[sel] = 255

        rgba = np.dstack([rgb, alpha])
        img = Image.fromarray(rgba, mode='RGBA')
        if max(h, w) > _NDVI_PNG_MAX_DIM:
            scale = _NDVI_PNG_MAX_DIM / max(h, w)
            img = img.resize(
                (max(int(w * scale), 1), max(int(h * scale), 1)),
                Image.LANCZOS,
            )
        pad = 20
        padded = Image.new('RGBA', (img.width + 2 * pad, img.height + 2 * pad), (245, 245, 245, 255))
        padded.paste(img, (pad, pad))
        buf = io.BytesIO()
        padded.save(buf, format='PNG', optimize=True)
        return buf.getvalue()
    except Exception as exc:
        logger.error('NDVI thumbnail render failed: %s', exc)
        return None


# Public entry point
def compute_vegetation_indices(plot, start_date=None, end_date=None, cloud_cover_threshold=20):
    """Compute mean vegetation indices for a plot from Sentinel-2 L2A.

    Returns a dict per spec (ndvi_mean/min/max, ndmi_mean, evi_mean, date_range,
    geometry_type, image_id, pixel_count, source) plus extra mean indices
    (ndre_mean, savi_mean, msavi_mean) and an ``image_png`` thumbnail. Returns
    ``{}`` when no usable imagery is found or a dependency is missing.
    """
    if not _NUMPY_OK:
        logger.error('numpy not installed')
        return {}
    np = _np

    geometry, geometry_type = _resolve_geometry(plot)
    if geometry is None:
        logger.warning('Plot has no boundary/GPS for vegetation analysis')
        return {}

    if end_date is None:
        end_date = datetime.date.today()
    if start_date is None:
        start_date = end_date - datetime.timedelta(days=_DEFAULT_DAYS_BACK)
    if isinstance(start_date, str):
        start_date = datetime.date.fromisoformat(start_date)
    if isinstance(end_date, str):
        end_date = datetime.date.fromisoformat(end_date)

    items = _search_items(geometry, start_date, end_date, cloud_cover_threshold)
    if not items:
        logger.warning('No Sentinel-2 items found for plot geometry')
        return {}

    # Try items from least to most cloudy until one yields valid pixels.
    for item in items:
        bands, aoi_mask = _read_stack(item, geometry)
        if bands is None:
            continue
        scl = bands['scl']
        bad = np.isin(scl.astype('int16'), _SCL_BAD)
        valid = aoi_mask & (~bad)
        pixel_count = int(np.count_nonzero(valid))
        if pixel_count == 0:
            continue

        indices = _compute_indices(bands, valid)
        ndvi_array = indices.pop('_ndvi_array')
        observed = (item.properties.get('datetime') or end_date.isoformat())[:10]

        return {
            'ndvi_mean': indices['ndvi']['mean'],
            'ndvi_min': indices['ndvi']['min'],
            'ndvi_max': indices['ndvi']['max'],
            'ndmi_mean': indices['ndmi']['mean'],
            'ndre_mean': indices['ndre']['mean'],
            'evi_mean': indices['evi']['mean'],
            'savi_mean': indices['savi']['mean'],
            'msavi_mean': indices['msavi']['mean'],
            'date_range': {'start': start_date.isoformat(), 'end': end_date.isoformat()},
            'geometry_type': geometry_type,
            'image_id': item.id,
            'observed_at': observed,
            'pixel_count': pixel_count,
            'source': SOURCE,
            'image_png': _ndvi_png(ndvi_array),
        }

    logger.warning('No cloud-free pixels for plot geometry in date range')
    return {}


# Weather (Open-Meteo current conditions, key-less)
WEATHER_URL = 'https://api.open-meteo.com/v1/forecast'


def fetch_current_weather(lat, lng):
    """Return current weather for a coordinate, or {} on any failure."""
    if lat is None or lng is None:
        return {}
    try:
        resp = requests.get(
            WEATHER_URL,
            params={
                'latitude': lat,
                'longitude': lng,
                'current': 'temperature_2m,relative_humidity_2m,wind_speed_10m,precipitation',
                'wind_speed_unit': 'ms',
                'forecast_days': 1,
            },
            timeout=10,
        )
        resp.raise_for_status()
        current = resp.json().get('current', {})
        return {
            'temperature': current.get('temperature_2m'),
            'humidity': current.get('relative_humidity_2m'),
            'wind_speed': current.get('wind_speed_10m'),
            'precipitation': current.get('precipitation'),
        }
    except Exception as exc:
        logger.error('Weather fetch failed: %s', exc)
        return {}


def _get_plot_recent_water_m3(plot, days=30):
    """Return total irrigation water received (m³) for a plot in the last ``days`` days.

    Uses DB-level aggregation to avoid loading Run objects into Python memory and
    avoids the per-row ``duration_seconds`` property which issues extra queries.
    """
    try:
        cutoff = timezone.now() - datetime.timedelta(days=days)
        discharge_rate = float(getattr(plot.zone.farm, 'discharge_rate', 0) or 0)
        if not discharge_rate:
            return 0.0

        start_qs = RunStatus.objects.filter(run=OuterRef('pk'), status='start').values('created_at')[:1]
        end_qs = RunStatus.objects.filter(run=OuterRef('pk'), status='end').values('created_at')[:1]

        result = (
            Run.objects
            .filter(outlet__plot=plot, created_at__gte=cutoff)
            .annotate(
                start_time=Subquery(start_qs),
                end_time=Subquery(end_qs),
            )
            .filter(start_time__isnull=False)
            .annotate(
                duration=ExpressionWrapper(
                    Case(
                        When(end_time__isnull=False, then=F('end_time') - F('start_time')),
                        default=Now() - F('start_time'),
                    ),
                    output_field=DurationField(),
                )
            )
            .aggregate(total=Sum('duration'))
        )
        total_duration = result['total']
        if not total_duration:
            return 0.0
        total_secs = total_duration.total_seconds()
        return round(discharge_rate * total_secs / 1000, 2)
    except Exception as exc:
        logger.error('Water calculation failed for plot %s: %s', getattr(plot, 'id', '?'), exc)
        return None


# Rule-based plot condition analysis (no AI)
def _clamp(value, low=0.0, high=100.0):
    return max(low, min(high, value))


# Centralized NDVI score ranges — single source of truth for all scoring, colors, labels.
# Boundaries align with pistachio reference constants above.
NDVI_SCORE_RANGES = {
    1: {"min": -1.0,  "max":  0.10, "score":  5,  "label": "Bare / desert",   "color": "#9e9e9e"},
    2: {"min":  0.10, "max":  0.20, "score": 20,  "label": "Very poor",       "color": "#d32f2f"},
    3: {"min":  0.20, "max":  0.35, "score": 40,  "label": "Poor / stressed", "color": "#ef6c00"},
    4: {"min":  0.35, "max":  0.50, "score": 65,  "label": "Moderate",        "color": "#fbc02d"},
    5: {"min":  0.50, "max":  0.70, "score": 85,  "label": "Good",            "color": "#7cb342"},
    6: {"min":  0.70, "max":  1.00, "score": 100, "label": "Excellent",       "color": "#1b5e20"},
}

# Centralized NDMI score ranges — single source of truth.
# PISTACHIO_NDMI_ADEQUATE_MIN (0.03) sits inside level 4 (adequate moisture).
# PISTACHIO_NDMI_STRESS_MIN (-0.12) sits inside level 2 (water stress).
NDMI_SCORE_RANGES = {
    1: {"min": -1.0,  "max": -0.20, "score":  5,  "label": "Severe drought",    "color": "#d32f2f"},
    2: {"min": -0.20, "max": -0.10, "score": 20,  "label": "Water stress",      "color": "#ef6c00"},
    3: {"min": -0.10, "max":  0.00, "score": 40,  "label": "Mild stress",       "color": "#fbc02d"},
    4: {"min":  0.00, "max":  0.10, "score": 65,  "label": "Adequate moisture", "color": "#4fc3f7"},
    5: {"min":  0.10, "max":  0.20, "score": 85,  "label": "Good moisture",     "color": "#0288d1"},
    6: {"min":  0.20, "max":  1.00, "score": 100, "label": "Well irrigated",    "color": "#01579b"},
}


def _score_from_ranges(value, ranges):
    """Return the score for a numeric value from a ranges dict."""
    if value is None:
        return None
    for r in ranges.values():
        if r["min"] <= value < r["max"]:
            return r["score"]
    return ranges[max(ranges.keys())]["score"]


def _ndvi_to_greenness(ndvi):
    """Pistachio-calibrated NDVI → greenness score from NDVI_SCORE_RANGES."""
    return _score_from_ranges(None if ndvi is None else float(ndvi), NDVI_SCORE_RANGES)


def _ndmi_to_moisture(ndmi):
    """Pistachio-calibrated NDMI → moisture score from NDMI_SCORE_RANGES."""
    return _score_from_ranges(None if ndmi is None else float(ndmi), NDMI_SCORE_RANGES)


def evaluate_plot_health(indices, weather, water_m3=None):
    """Rule-based assessment from vegetation indices + current weather + irrigation water.

    ``indices`` keys: ndvi, ndmi, ndre, evi, savi, msavi (any may be None).
    ``water_m3``: total irrigation water received in recent period (m³), or None.
    Returns a JSON-serializable dict with normalized scores, an overall health
    score, detected problems (with severity), and improvement suggestions.
    """
    indices = indices or {}
    weather = weather or {}

    ndvi = indices.get('ndvi')
    ndmi = indices.get('ndmi')
    ndre = indices.get('ndre')

    greenness = _ndvi_to_greenness(ndvi)
    moisture = _ndmi_to_moisture(ndmi)

    problems = []
    suggestions = []

    if greenness is not None:
        if greenness is not None and greenness <= 20:
            problems.append({
                'title': _('Weak vegetation cover'),
                'severity': 'high',
                'description': _('Low greenness index (NDVI=%(ndvi)s). Pistachio healthy range: NDVI ≥ 0.35.') % {'ndvi': ndvi},
            })
            suggestions.append(_('Check plant nutrition, pests, and irrigation adequacy. For pistachio, target NDVI ≥ 0.35.'))
        elif greenness <= 40:
            problems.append({
                'title': _('Moderate vegetation cover'),
                'severity': 'medium',
                'description': _('Moderate greenness index (NDVI=%(ndvi)s). Pistachio optimal NDVI: 0.35–0.65.') % {'ndvi': ndvi},
            })
            suggestions.append(_('Periodic monitoring and improved nutrition program recommended. Pistachio optimal NDVI: 0.35–0.65.'))

    if moisture is not None:
        if moisture is not None and moisture <= 20:
            problems.append({
                'title': _('Moisture stress / water deficit'),
                'severity': 'high',
                'description': _('Low moisture index (NDMI=%(ndmi)s). Pistachio requires NDMI ≥ 0.03.') % {'ndmi': ndmi},
            })
            suggestions.append(_('Increase irrigation frequency or volume. Pistachio target NDMI ≥ 0.03.'))
        elif moisture <= 40:
            problems.append({
                'title': _('Soil moisture declining'),
                'severity': 'medium',
                'description': _('Moisture index declining (NDMI=%(ndmi)s). Pistachio adequate range: NDMI 0.03–0.25.') % {'ndmi': ndmi},
            })
            suggestions.append(_('Monitor irrigation schedule carefully. Pistachio adequate NDMI: 0.03–0.25.'))

    if ndre is not None and float(ndre) < 0.2:
        problems.append({
            'title': _('Possible nitrogen deficiency'),
            'severity': 'medium',
            'description': _('Low red-edge index (NDRE=%(ndre)s).') % {'ndre': ndre},
        })
        suggestions.append(_('Check nitrogen fertilisation status.'))

    temp = weather.get('temperature')
    wind = weather.get('wind_speed')
    precip = weather.get('precipitation')

    heat_penalty = 0
    if temp is not None:
        if temp >= 43:
            heat_penalty = 15
            problems.append({
                'title': _('Severe heat stress'),
                'severity': 'high',
                'description': _('Current temperature is very high (%(temp)s°C).') % {'temp': temp},
            })
            suggestions.append(_('Irrigate during cooler hours and increase frequency.'))
        elif temp >= 38:
            heat_penalty = 8
            problems.append({
                'title': _('Heat stress risk'),
                'severity': 'medium',
                'description': _('Current temperature is high (%(temp)s°C).') % {'temp': temp},
            })
            suggestions.append(_('Irrigate during cooler hours.'))

    if wind is not None and wind >= 8:
        problems.append({
            'title': _('High wind speed'),
            'severity': 'low',
            'description': _('Current wind speed is high (%(wind)s m/s).') % {'wind': wind},
        })
        suggestions.append(_('Avoid sprinkler irrigation during strong winds.'))

    if precip is not None and precip > 1:
        suggestions.append(_('Reduce irrigation volume due to recent precipitation.'))

    if water_m3 is not None:
        if water_m3 == 0:
            problems.append({
                'title': _('No irrigation recorded'),
                'severity': 'high',
                'description': _('No irrigation water recorded in the last 30 days.'),
            })
            suggestions.append(_('Check irrigation system and schedule.'))
        elif water_m3 < 10:
            problems.append({
                'title': _('Very low irrigation'),
                'severity': 'medium',
                'description': _('Only %(water)s m³ of irrigation water in the last 30 days.') % {'water': water_m3},
            })
            suggestions.append(_('Review and increase irrigation schedule.'))

    # Water score: converts m³ to 0-100 contribution
    if water_m3 is None:
        water_score = None
    elif water_m3 == 0:
        water_score = 0.0
    elif water_m3 < 10:
        water_score = 30.0
    elif water_m3 < 50:
        water_score = 70.0
    else:
        water_score = 100.0

    # Precipitation bonus: recent rain reduces irrigation need (up to +5)
    precip_bonus = 5 if (precip is not None and precip > 2) else 0

    # NDVI/NDMI form the main score (90%); water is a secondary factor (10%);
    # weather contributes only via heat_penalty and precip_bonus.
    _parts = []
    if greenness is not None:
        _parts.append((greenness, 0.50))
    if moisture is not None:
        _parts.append((moisture, 0.40))
    if water_score is not None:
        _parts.append((water_score, 0.10))

    if _parts:
        _total_w = sum(w for _, w in _parts)
        base = sum(v * w for v, w in _parts) / _total_w
    else:
        base = None

    if base is None:
        health_score = None
        summary = _('Insufficient data for plot condition analysis.')
    else:
        health_score = int(round(_clamp(base - heat_penalty + precip_bonus)))
        if health_score >= 70:
            summary = _('Overall plot condition is good.')
        elif health_score >= 50:
            summary = _('Plot condition is moderate and requires monitoring.')
        else:
            summary = _('Plot condition is poor and requires immediate attention.')

    return {
        'greenness_score': greenness,
        'moisture_score': moisture,
        'health_score': health_score,
        'ndvi': float(ndvi) if ndvi is not None else None,
        'ndmi': float(ndmi) if ndmi is not None else None,
        'ndre': float(ndre) if ndre is not None else None,
        'evi': float(indices.get('evi')) if indices.get('evi') is not None else None,
        'savi': float(indices.get('savi')) if indices.get('savi') is not None else None,
        'msavi': float(indices.get('msavi')) if indices.get('msavi') is not None else None,
        'water_m3': water_m3,
        'weather': weather,
        'problems': problems,
        'suggestions': suggestions,
        'summary': summary,
        'has_data': base is not None,
    }


def analyze_plot_condition(plot):
    """Gather a plot's latest vegetation indices + current weather + recent water and evaluate it.

    Reads the most recent ``PlotVegetationIndex`` for the plot and the weather at
    the plot's GPS/centroid, then runs :func:`evaluate_plot_health`. No AI.
    """
    vi = PlotVegetationIndex.objects.filter(plot=plot).order_by('-observed_at', '-id').first()
    indices = {}
    observed_at = None
    if vi is not None:
        observed_at = vi.observed_at.isoformat() if vi.observed_at else None
        indices = {
            'ndvi': vi.ndvi, 'ndmi': vi.ndmi, 'ndre': vi.ndre,
            'evi': vi.evi, 'savi': vi.savi, 'msavi': vi.msavi,
        }

    lat = _plot_attr(plot, 'gps_lat')
    lng = _plot_attr(plot, 'gps_lng')
    if (lat is None or lng is None) and _plot_attr(plot, 'boundary'):
        geometry, _ = _resolve_geometry(plot)
        if geometry is not None:
            ring = geometry['coordinates'][0]
            lng = sum(c[0] for c in ring[:-1]) / max(len(ring) - 1, 1)
            lat = sum(c[1] for c in ring[:-1]) / max(len(ring) - 1, 1)

    weather = fetch_current_weather(float(lat), float(lng)) if lat is not None and lng is not None else {}
    water_m3 = _get_plot_recent_water_m3(plot)

    result = evaluate_plot_health(indices, weather, water_m3=water_m3)
    result['observed_at'] = observed_at
    return result
