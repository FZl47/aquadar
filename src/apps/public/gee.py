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

# Pistachio (Pistacia vera) reference NDVI/NDMI ranges.
# Calibrated against Kerman/Rafsanjan Sentinel-2 observations: even well-managed
# orchards rarely exceed plot-mean NDVI 0.30 (canopy is ≤30% of pixel area, the
# rest is bare soil between trees) and semi-arid NDMI typically sits negative.
# These thresholds reflect that — anything 0.18+ NDVI is a healthy orchard,
# 0.30+ is vigorous; NDMI ≥ -0.05 is adequate for drought-tolerant pistachio.
PISTACHIO_NDVI_HEALTHY_MIN = 0.18    # NDVI ≥ 0.18 → healthy pistachio canopy
PISTACHIO_NDVI_VIGOROUS_MIN = 0.30   # NDVI ≥ 0.30 → vigorous canopy (peak season)
PISTACHIO_NDVI_STRESSED_MIN = 0.10   # NDVI 0.10–0.18 → sparse / young / stressed
PISTACHIO_NDMI_ADEQUATE_MIN = -0.05  # NDMI ≥ -0.05 → adequate (drought-tolerant)
PISTACHIO_NDMI_STRESS_MIN = -0.20    # NDMI -0.20 to -0.05 → mild water stress

logger = logging.getLogger(__name__)

STAC_URL = 'https://planetarycomputer.microsoft.com/api/stac/v1'
COLLECTION = 'sentinel-2-l2a'
SOURCE = 'Sentinel-2 / Microsoft Planetary Computer'

# SCL classes to mask: 0 no-data, 1 saturated, 3 cloud shadow, 8 cloud medium,
# 9 cloud high, 10 thin cirrus, 11 snow/ice.
_SCL_BAD = (0, 1, 3, 8, 9, 10, 11)

# Planetary Computer Sentinel-2 L2A asset keys.
# NDMI uses B8A (narrow NIR, 865 nm, 20 m) rather than the broad B08: the
# standard Gao (1996) moisture index pairs 860 nm NIR with SWIR1 (B11), and
# both bands share the same 20 m native grid, so the ratio is spectrally and
# spatially consistent. B08 (broad NIR, 10 m) stays for NDVI/EVI/SAVI/MSAVI.
_BANDS = {
    'red': 'B04',
    'nir': 'B08',
    'nir08': 'B8A',
    'swir': 'B11',
    'rededge': 'B05',
    'blue': 'B02',
    'green': 'B03',
    'scl': 'SCL',
}

_DEFAULT_DAYS_BACK = 60
_POINT_BUFFER_M = 30  # GPS fallback buffer (tight for small pistachio plots)
_TARGET_RES = 10.0    # metres (Sentinel-2 native resolution for B02/B03/B04/B08)


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
        # Project the polygon *itself* to UTM and take the bounding box of the
        # projected vertices. transform_bounds samples only the lat/lng bbox
        # corners; for non-trivial polygons (square plots, tilted geometries) it
        # can return a tighter rectangle than the actual UTM extent — clipping
        # half the AOI off the raster grid.
        geom_utm = transform_geom('EPSG:4326', target_crs, geometry)
        utm_coords = []
        for ring in geom_utm.get('coordinates') or []:
            for pt in ring:
                if len(pt) >= 2:
                    utm_coords.append((float(pt[0]), float(pt[1])))
        if utm_coords:
            xs = [c[0] for c in utm_coords]
            ys = [c[1] for c in utm_coords]
            bx0, by0, bx1, by1 = min(xs), min(ys), max(xs), max(ys)
        else:
            bx0, by0, bx1, by1 = transform_bounds('EPSG:4326', target_crs, minx, miny, maxx, maxy)
    except Exception as exc:
        logger.error('AOI reprojection failed: %s', exc)
        return None, None

    # Add a half-pixel buffer so vertices on the bbox edge don't round-fall outside the grid.
    bx0 -= _TARGET_RES / 2
    by0 -= _TARGET_RES / 2
    bx1 += _TARGET_RES / 2
    by1 += _TARGET_RES / 2

    width = max(int(math.ceil((bx1 - bx0) / _TARGET_RES)), 1)
    height = max(int(math.ceil((by1 - by0) / _TARGET_RES)), 1)
    transform = from_origin(bx0, by1, _TARGET_RES, _TARGET_RES)

    assets = item.assets
    for name, key in _BANDS.items():
        if assets.get(key) is None:
            logger.warning('Item %s missing asset %s', item.id, key)
            return None, None

    def _fetch_band(name, key):
        if name == 'scl':
            resampling = Resampling.nearest
        elif name in ('swir', 'nir08'):
            # B11 and B8A are 20 m native; cubic resample to the 10 m grid
            # preserves gradient detail better than bilinear and improves NDMI
            # sharpness.
            resampling = Resampling.cubic
        else:
            resampling = Resampling.bilinear
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
        aoi_mask = geometry_mask(
            [geom_utm], out_shape=(height, width), transform=transform, invert=True,
        )
    except Exception as exc:
        logger.error('AOI mask build failed: %s', exc)
        return None, None

    return bands, aoi_mask


def _dilate_mask(mask, iterations=1):
    """Binary-dilate a boolean mask with a 3×3 kernel (numpy-only).

    SCL routinely under-detects cloud/shadow fringes by a pixel or two; growing
    the bad-pixel mask keeps that contaminated halo out of the statistics.
    """
    np = _np
    out = mask
    for _i in range(iterations):
        padded = np.pad(out, 1, mode='edge')
        out = (
            padded[0:-2, 0:-2] | padded[0:-2, 1:-1] | padded[0:-2, 2:]
            | padded[1:-1, 0:-2] | padded[1:-1, 1:-1] | padded[1:-1, 2:]
            | padded[2:, 0:-2] | padded[2:, 1:-1] | padded[2:, 2:]
        )
    return out


# Index computation
def _compute_indices(bands, valid):
    import numpy as np

    scale = 1.0 / 10000.0
    nir = bands['nir'] * scale
    nir08 = bands['nir08'] * scale
    red = bands['red'] * scale
    swir = bands['swir'] * scale
    rededge = bands['rededge'] * scale
    blue = bands['blue'] * scale

    with np.errstate(divide='ignore', invalid='ignore'):
        ndvi = (nir - red) / (nir + red)
        # Gao (1996) NDMI: narrow NIR (B8A) with SWIR1 (B11) — both 20 m native.
        ndmi = (nir08 - swir) / (nir08 + swir)
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
            # min/max as 2nd/98th percentiles — raw extremes on a small plot are
            # dominated by single-pixel sensor noise / residual cloud fringe and
            # mislead the UI range display.
            out[name] = {
                'mean': round(float(np.mean(finite)), 4),
                'min': round(float(np.percentile(finite, 2)), 4),
                'max': round(float(np.percentile(finite, 98)), 4),
            }
    out['_ndvi_array'] = np.where(valid, ndvi, np.nan)
    out['_ndmi_array'] = np.where(valid, ndmi, np.nan)
    return out


# NDVI colour ramp — pistachio-calibrated and aligned with NDVI_SCORE_RANGES so
# the map colour matches the verdict the scoring gives: 0.10–0.15 stressed
# (orange), 0.15–0.20 acceptable (yellow), 0.20–0.30 healthy (green), 0.30+
# vigorous (dark green). Previously green only started near 0.26, so a plot the
# score called "healthy" (mean 0.21, score 92) rendered alarming orange.
_NDVI_RAMP = (
    (-0.05, ( 33, 150, 243)),  # water / snow
    ( 0.03, (158, 158, 158)),  # bare soil / urban
    ( 0.06, (183,  28,  28)),  # very poor / struggling
    ( 0.10, (229,  57,  53)),  # stressed pistachio (low)
    ( 0.13, (239, 108,   0)),  # stressed pistachio
    ( 0.15, (251, 192,  45)),  # acceptable pistachio
    ( 0.18, (212, 225,  87)),  # acceptable → healthy transition
    ( 0.20, (156, 204, 101)),  # healthy pistachio (low)
    ( 0.25, (124, 179,  66)),  # healthy pistachio
    ( 0.30, ( 67, 160,  71)),  # vigorous pistachio (low)
    ( 0.40, ( 46, 125,  50)),  # vigorous pistachio
    (10.0,  ( 27,  94,  32)),  # excellent / dense crop
)
_NDVI_PNG_SIZE = 1024  # final PNG output size (px) — high resolution thumbnail.
# Bilinear upsample factor applied to NDVI/NDMI/satellite arrays before colour
# ramp + final resize. 8× turns a 10×10 sensor grid into an 80×80 smoothed grid,
# making the final 1024 PNG look continuous instead of "pixel pixel" blocky.
_RENDER_UPSCALE = 8
# NDMI uses a higher factor because SWIR B11 is 20 m native (half the spatial
# resolution of NIR/red), so the effective NDMI grid is sparser and needs more
# pre-upsampling to look as sharp as NDVI.
_NDMI_RENDER_UPSCALE = 16

# NDMI colour ramp — pistachio-calibrated, dense stops around the irrigation
# decision range (-0.15 to 0.10) so per-pixel differences stay visually
# distinguishable instead of all blending into one band. Pistachio is
# drought-tolerant: NDMI is typically negative in semi-arid orchards, so the
# adequate-moisture band starts at -0.05 (not 0.00).
_NDMI_RAMP = (
    (-0.35, (127,   0,   0)),  # extreme drought
    (-0.30, (183,  28,  28)),
    (-0.25, (198,  40,  40)),
    (-0.22, (211,  47,  47)),  # severe drought
    (-0.19, (220,  60,  35)),
    (-0.16, (230,  74,  25)),  # water stress
    (-0.13, (235,  90,  12)),
    (-0.10, (239, 108,   0)),  # mild stress
    (-0.07, (245, 150,  20)),
    (-0.05, (251, 192,  45)),  # borderline
    (-0.02, (220, 215,  90)),
    ( 0.00, (174, 213, 129)),  # adequate (low)
    ( 0.02, (130, 210, 175)),
    ( 0.05, ( 79, 195, 247)),  # adequate
    ( 0.08, ( 55, 188, 246)),
    ( 0.10, ( 41, 182, 246)),  # good (low)
    ( 0.14, ( 20, 160, 230)),
    ( 0.18, (  2, 136, 209)),  # good moisture
    ( 0.25, (  1, 110, 180)),
    (10.0,  (  1,  87, 155)),  # well irrigated
)


def _upsample_index(arr, factor=_RENDER_UPSCALE):
    """Bilinear-upsample a float index array (NaN-aware).

    NaNs are replaced with 0 before resize (PIL can't handle NaNs), but a
    parallel binary "valid" mask is upsampled with NEAREST so the original
    masked region is preserved without smearing bogus values across the edge.
    Returns (smooth_arr, valid_mask). Values where ``valid_mask`` is False
    should be ignored / drawn transparent.
    """
    np = _np
    Image = _PilImage
    h, w = arr.shape
    if factor <= 1 or h == 0 or w == 0:
        return arr, np.isfinite(arr)
    nw, nh = max(int(w * factor), 1), max(int(h * factor), 1)

    finite = np.isfinite(arr)
    # Fill NaNs with the finite median (not 0) — bilinear smearing at the AOI
    # edge then biases toward typical data instead of dragging boundary pixels
    # toward a fake "0" colour.
    if finite.any():
        fill = float(np.median(arr[finite]))
    else:
        fill = 0.0
    src = np.where(finite, arr, fill).astype('float32')
    smooth_img = Image.fromarray(src, mode='F').resize((nw, nh), Image.BILINEAR)
    smooth = np.array(smooth_img)

    mask_src = (finite.astype('uint8') * 255)
    mask_img = Image.fromarray(mask_src, mode='L').resize((nw, nh), Image.NEAREST)
    valid = np.array(mask_img) > 0
    return smooth, valid


def _apply_ramp_linear(values, valid, ramp):
    """Map a float array to RGBA via linear interpolation between ramp stops.

    Stops are ``((threshold, (r, g, b)), ...)`` sorted ascending. Below the
    first stop returns the first colour; above the last returns the last.
    Between adjacent stops interpolates each channel linearly — gives a smooth
    gradient instead of the previous stepped/posterised look.
    """
    np = _np
    h, w = values.shape
    rgb = np.zeros((h, w, 3), dtype='uint8')

    stops = list(ramp)
    thresholds = np.array([s[0] for s in stops], dtype='float32')
    colors = np.array([s[1] for s in stops], dtype='float32')

    clipped = np.clip(values, thresholds[0], thresholds[-1] - 1e-6)
    idx = np.searchsorted(thresholds, clipped, side='right') - 1
    idx = np.clip(idx, 0, len(stops) - 2)

    lo_t = thresholds[idx]
    hi_t = thresholds[idx + 1]
    span = np.maximum(hi_t - lo_t, 1e-9)
    frac = np.clip((clipped - lo_t) / span, 0.0, 1.0)[..., None]
    lo_c = colors[idx]
    hi_c = colors[idx + 1]
    blended = lo_c + (hi_c - lo_c) * frac

    rgb[:] = np.clip(blended, 0, 255).astype('uint8')
    alpha = np.where(valid, 255, 0).astype('uint8')
    return rgb, alpha


def _index_png(arr, ramp, label, upscale=_RENDER_UPSCALE):
    """Render a vegetation/moisture index array to a smooth coloured PNG."""
    if not _NUMPY_OK or not _PIL_OK:
        return None
    np = _np
    Image = _PilImage
    try:
        smooth, valid = _upsample_index(arr, upscale)
        rgb, alpha = _apply_ramp_linear(smooth, valid, ramp)
        rgba = np.dstack([rgb, alpha])
        img = Image.fromarray(rgba, mode='RGBA')
        h, w = rgba.shape[:2]
        scale = _NDVI_PNG_SIZE / max(h, w, 1)
        img = img.resize(
            (max(int(w * scale), 1), max(int(h * scale), 1)),
            Image.LANCZOS,
        )
        buf = io.BytesIO()
        img.save(buf, format='PNG', optimize=True)
        return buf.getvalue()
    except Exception as exc:
        logger.error('%s thumbnail render failed: %s', label, exc)
        return None


def _ndvi_png(ndvi_array):
    """Render an NDVI array to a smooth coloured PNG (bytes)."""
    return _index_png(ndvi_array, _NDVI_RAMP, 'NDVI')


def _ndmi_png(ndmi_array):
    """Render an NDMI array to a smooth coloured PNG (bytes) with transparent BG."""
    return _index_png(ndmi_array, _NDMI_RAMP, 'NDMI', upscale=_NDMI_RENDER_UPSCALE)


def _satellite_png(bands, aoi_mask):
    """Render a true-colour (R/G/B) PNG from Sentinel-2 B04/B03/B02.

    Each band is bilinearly upsampled by ``_RENDER_UPSCALE`` before being
    composited so the visible texture matches the smoothed NDVI/NDMI rasters
    instead of looking blockier.
    """
    if not _NUMPY_OK or not _PIL_OK:
        return None
    np = _np
    Image = _PilImage
    try:
        scale = 1.0 / 10000.0

        # Adaptive contrast: stretch each band between its 2nd/98th percentile
        # over AOI pixels instead of a fixed gain. Desert scenes with a fixed
        # 3.5× gain either wash out (bright soil) or stay murky (low sun angle);
        # the percentile stretch adapts per scene. A shared low/high across the
        # three bands would preserve exact hue ratios but kills contrast when
        # one band dominates, so stretch per band with a floor on the span.
        def _stretch_limits(band):
            vals = band[aoi_mask] * scale
            vals = vals[_np.isfinite(vals)]
            if vals.size < 16:
                return 0.0, 1.0 / 3.5  # fallback ≈ old fixed gain
            lo = float(_np.percentile(vals, 2))
            hi = float(_np.percentile(vals, 98))
            if hi - lo < 0.02:  # near-uniform scene — avoid noise amplification
                mid = (hi + lo) / 2
                lo, hi = mid - 0.01, mid + 0.01
            return lo, hi

        def _upsample_band(band):
            h, w = band.shape
            if _RENDER_UPSCALE <= 1 or h == 0 or w == 0:
                return band.astype('float32')
            nw, nh = max(int(w * _RENDER_UPSCALE), 1), max(int(h * _RENDER_UPSCALE), 1)
            img = Image.fromarray(band.astype('float32'), mode='F').resize((nw, nh), Image.BILINEAR)
            return np.array(img)

        def _band_to_u8(band):
            lo, hi = _stretch_limits(band)
            up = _upsample_band(band) * scale
            norm = np.clip((up - lo) / max(hi - lo, 1e-6), 0, 1)
            # Mild gamma lift so shadowed rows between tree lines stay readable.
            norm = norm ** 0.9
            return (norm * 255).astype('uint8')

        r = _band_to_u8(bands['red'])
        g = _band_to_u8(bands['green'])
        b = _band_to_u8(bands['blue'])

        mask_img = Image.fromarray((aoi_mask.astype('uint8') * 255), mode='L').resize(
            (r.shape[1], r.shape[0]), Image.NEAREST,
        )
        alpha = np.array(mask_img).astype('uint8')

        rgba = np.dstack([r, g, b, alpha])
        img = Image.fromarray(rgba, mode='RGBA')
        h_px, w_px = rgba.shape[:2]
        scale = _NDVI_PNG_SIZE / max(h_px, w_px, 1)
        img = img.resize((max(int(w_px * scale), 1), max(int(h_px * scale), 1)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format='PNG', optimize=True)
        return buf.getvalue()
    except Exception as exc:
        logger.error('Satellite thumbnail render failed: %s', exc)
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

    # Scan top-N candidates and pick the one with the best AOI coverage —
    # plots that straddle two Sentinel-2 tiles otherwise get rendered from a
    # single partial tile, leaving half the plot transparent.
    candidate_limit = 6
    coverage_target = 0.95
    best = None  # (ratio, item, bands, aoi_mask, valid, pixel_count)
    for item in items[:candidate_limit]:
        bands, aoi_mask = _read_stack(item, geometry)
        if bands is None:
            continue
        scl = bands['scl']
        bad = _dilate_mask(np.isin(scl.astype('int16'), _SCL_BAD))
        # Pixels with zero reflectance in red/NIR fall outside the tile footprint
        # (Sentinel-2 no-data) and must be excluded too.
        nodata = (bands['red'] == 0) | (bands['nir'] == 0)
        valid = aoi_mask & (~bad) & (~nodata)
        pixel_count = int(np.count_nonzero(valid))
        if pixel_count == 0:
            continue
        aoi_total = int(np.count_nonzero(aoi_mask)) or 1
        ratio = pixel_count / aoi_total
        if best is None or ratio > best[0]:
            best = (ratio, item, bands, aoi_mask, valid, pixel_count)
        if ratio >= coverage_target:
            break

    if best is None:
        logger.warning('No cloud-free pixels for plot geometry in date range')
        return {}

    ratio, item, bands, aoi_mask, valid, pixel_count = best
    indices = _compute_indices(bands, valid)
    ndvi_array = indices.pop('_ndvi_array')
    ndmi_array = indices.pop('_ndmi_array')
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
        'coverage_ratio': round(ratio, 3),
        'source': SOURCE,
        'image_png': _ndvi_png(ndvi_array),
        'moisture_image_png': _ndmi_png(ndmi_array),
        'satellite_image_png': _satellite_png(bands, valid),
    }


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


# Centralized NDVI score ranges — pistachio-calibrated against real Sentinel-2
# observations of Kerman/Rafsanjan orchards. Even peak-season vigorous
# orchards rarely exceed plot-mean NDVI 0.30; 0.18 is already healthy, 0.10 is
# young/sparse. Scoring shifted so a 0.20 plot reads as healthy, not "poor".
NDVI_SCORE_RANGES = {
    1: {"min": -1.0,  "max":  0.05, "score":  5,   "label": "Bare / desert",        "color": "#9e9e9e"},
    2: {"min":  0.05, "max":  0.10, "score": 30,   "label": "Very poor",            "color": "#d32f2f"},
    3: {"min":  0.10, "max":  0.15, "score": 55,   "label": "Stressed pistachio",   "color": "#ef6c00"},
    4: {"min":  0.15, "max":  0.20, "score": 78,   "label": "Acceptable pistachio", "color": "#fbc02d"},
    5: {"min":  0.20, "max":  0.30, "score": 92,   "label": "Healthy pistachio",    "color": "#7cb342"},
    6: {"min":  0.30, "max":  1.00, "score": 100,  "label": "Vigorous pistachio",   "color": "#1b5e20"},
}

# Centralized NDMI score ranges — pistachio-calibrated (drought-tolerant crop
# in semi-arid climate). NDMI sits naturally negative for pistachio orchards,
# so adequate-moisture band starts at -0.05 (not 0.00). Mild stress no longer
# auto-fails the plot — pistachio handles it.
NDMI_SCORE_RANGES = {
    1: {"min": -1.0,  "max": -0.25, "score": 10,   "label": "Severe drought",    "color": "#d32f2f"},
    2: {"min": -0.25, "max": -0.15, "score": 40,   "label": "Water stress",      "color": "#ef6c00"},
    3: {"min": -0.15, "max": -0.05, "score": 65,   "label": "Mild stress",       "color": "#fbc02d"},
    4: {"min": -0.05, "max":  0.05, "score": 85,   "label": "Adequate moisture", "color": "#4fc3f7"},
    5: {"min":  0.05, "max":  0.15, "score": 95,   "label": "Good moisture",     "color": "#0288d1"},
    6: {"min":  0.15, "max":  1.00, "score": 100,  "label": "Well irrigated",    "color": "#01579b"},
}


def _score_from_ranges(value, ranges):
    """Return the score for a numeric value from a ranges dict."""
    if value is None:
        return None
    for r in ranges.values():
        if r["min"] <= value < r["max"]:
            return r["score"]
    return ranges[max(ranges.keys())]["score"]


# Pistachio percent mapping. Greenness/moisture % is now a linear function of the
# raw NDVI/NDMI rate (-1..1) instead of a stepped band score. Pistachio plots get
# a *boosted* rate: plot-mean NDVI rarely exceeds 0.30 even on a vigorous orchard,
# so [0, 0.30] is stretched to [0, 100]% instead of using the full [-1, 1] range
# (which would cap a healthy pistachio at ~65%). NDMI [-0.20, 0.15] → [0, 100]%.
PISTACHIO_NDVI_PCT_MAX = PISTACHIO_NDVI_VIGOROUS_MIN  # NDVI 0.30 → 100%
PISTACHIO_NDMI_PCT_MIN = PISTACHIO_NDMI_STRESS_MIN    # NDMI -0.20 → 0%
PISTACHIO_NDMI_PCT_MAX = 0.15                          # NDMI 0.15 → 100%


def _ndvi_to_greenness(ndvi):
    """NDVI rate → pistachio-boosted greenness percent (0–100).

    Linear map: NDVI ≤ 0 → 0%, NDVI ≥ PISTACHIO_NDVI_PCT_MAX (0.30) → 100%.
    """
    if ndvi is None:
        return None
    v = max(-1.0, min(1.0, float(ndvi)))
    if v <= 0:
        return 0
    pct = (v / PISTACHIO_NDVI_PCT_MAX) * 100.0
    return int(round(max(0.0, min(100.0, pct))))


def _ndmi_to_moisture(ndmi):
    """NDMI rate → pistachio-boosted moisture percent (0–100).

    Linear map between PISTACHIO_NDMI_PCT_MIN (-0.20 → 0%) and
    PISTACHIO_NDMI_PCT_MAX (0.15 → 100%). Drought-tolerant semi-arid pistachio
    sits naturally negative, so the lower bound is below 0.
    """
    if ndmi is None:
        return None
    v = max(-1.0, min(1.0, float(ndmi)))
    span = PISTACHIO_NDMI_PCT_MAX - PISTACHIO_NDMI_PCT_MIN
    if span <= 0:
        return None
    pct = (v - PISTACHIO_NDMI_PCT_MIN) / span * 100.0
    return int(round(max(0.0, min(100.0, pct))))


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
        if greenness <= 30:
            problems.append({
                'title': _('Weak vegetation cover'),
                'severity': 'high',
                'description': _('Low greenness index (NDVI=%(ndvi)s). Pistachio healthy range: NDVI ≥ 0.18 (orchards with wide tree spacing).') % {'ndvi': ndvi},
            })
            suggestions.append(_('Check plant nutrition, pests, and irrigation. For pistachio orchards, target plot-mean NDVI ≥ 0.18.'))
        elif greenness <= 55:
            problems.append({
                'title': _('Marginal pistachio vigour'),
                'severity': 'medium',
                'description': _('Borderline greenness index (NDVI=%(ndvi)s). Healthy pistachio plot-mean: NDVI 0.18–0.30.') % {'ndvi': ndvi},
            })
            suggestions.append(_('Monitor canopy and nutrition. Pistachio plot-mean NDVI typically peaks at 0.20–0.30; do not expect dense-crop values (0.5+).'))

    if moisture is not None:
        if moisture <= 40:
            problems.append({
                'title': _('Moisture stress / water deficit'),
                'severity': 'high',
                'description': _('Low moisture index (NDMI=%(ndmi)s). Pistachio adequate: NDMI ≥ -0.05.') % {'ndmi': ndmi},
            })
            suggestions.append(_('Increase irrigation frequency or volume. Pistachio target NDMI ≥ -0.05 (drought-tolerant but stressed below).'))
        elif moisture <= 65:
            problems.append({
                'title': _('Soil moisture borderline'),
                'severity': 'medium',
                'description': _('Moisture index borderline (NDMI=%(ndmi)s). Pistachio adequate range: NDMI -0.05–0.15.') % {'ndmi': ndmi},
            })
            suggestions.append(_('Monitor irrigation schedule. Pistachio adequate NDMI: -0.05–0.15.'))

    if ndre is not None and float(ndre) < 0.10:
        problems.append({
            'title': _('Possible nitrogen deficiency'),
            'severity': 'medium',
            'description': _('Low red-edge index (NDRE=%(ndre)s) for pistachio canopy.') % {'ndre': ndre},
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

    # Weighting: NDVI is the primary indicator for pistachio orchard health
    # (canopy fraction), NDMI is secondary (semi-arid orchards run NDMI low
    # without being unhealthy), water is a sanity factor. Weather contributes
    # only via heat_penalty and precip_bonus.
    _parts = []
    if greenness is not None:
        _parts.append((greenness, 0.60))
    if moisture is not None:
        _parts.append((moisture, 0.25))
    if water_score is not None:
        _parts.append((water_score, 0.15))

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
