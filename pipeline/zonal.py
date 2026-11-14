"""Area-weighted zonal statistics (the report's harmonisation rule).

    x_bar(F, t) = sum_p w_p * x(p, t) / sum_p w_p

where w_p is the share of pixel p that lies inside field polygon F. Weights come from
rasterising the polygon on a grid `supersample` times finer than the raster, so edge
pixels count in proportion to how much of them the field covers. The same function is
used for 30 m Landsat pixels and for 10 km grid cells.
"""
from __future__ import annotations

import numpy as np
from affine import Affine
from rasterio import features


def coverage_weights(geom, transform: Affine, shape: tuple[int, int], supersample: int = 5) -> np.ndarray:
    """Fraction (0-1) of each raster cell covered by `geom` (same CRS as the raster)."""
    h, w = shape
    fine = transform * Affine.scale(1.0 / supersample, 1.0 / supersample)
    mask = features.rasterize(
        [(geom, 1)], out_shape=(h * supersample, w * supersample), transform=fine,
        fill=0, dtype="uint8", all_touched=False,
    )
    return mask.reshape(h, supersample, w, supersample).mean(axis=(1, 3)).astype("float64")


def weighted_mean(values: np.ndarray, weights: np.ndarray, min_valid_fraction: float = 0.0):
    """Area-weighted mean ignoring NaN. Returns (mean, valid_fraction).

    valid_fraction is the share of the polygon's area that had valid data; callers use it
    to drop cloudy or partly-covered observations instead of trusting a few pixels.
    """
    v = np.asarray(values, dtype="float64")
    w = np.asarray(weights, dtype="float64")
    total = w.sum()
    if total <= 0:
        return float("nan"), 0.0
    ok = np.isfinite(v) & (w > 0)
    wv = w[ok].sum()
    frac = float(wv / total)
    if wv <= 0 or frac < min_valid_fraction:
        return float("nan"), frac
    return float((v[ok] * w[ok]).sum() / wv), frac


def weighted_fractions(classes: np.ndarray, weights: np.ndarray) -> dict[int, float]:
    """Area share of each integer class inside the polygon (sums to 1)."""
    c = np.asarray(classes)
    w = np.asarray(weights, dtype="float64")
    total = w.sum()
    out: dict[int, float] = {}
    if total <= 0:
        return out
    for val in np.unique(c[w > 0]):
        out[int(val)] = float(w[c == val].sum() / total)
    return out


def grid_cell_weights(geom, lons: np.ndarray, lats: np.ndarray) -> np.ndarray:
    """Coverage weights for a regular lon/lat grid given cell-centre coordinates.

    `lons` ascending, `lats` ascending or descending; returns array [len(lats), len(lons)].
    """
    lons = np.asarray(lons, dtype="float64")
    lats = np.asarray(lats, dtype="float64")
    dx = float(np.abs(np.diff(lons)).mean()) if lons.size > 1 else 0.1
    dy = float(np.abs(np.diff(lats)).mean()) if lats.size > 1 else 0.1
    descending = lats.size > 1 and lats[0] > lats[-1]
    lat_sorted = lats if descending else lats[::-1]
    transform = Affine(dx, 0, lons.min() - dx / 2, 0, -dy, lat_sorted[0] + dy / 2)
    w = coverage_weights(geom, transform, (lats.size, lons.size), supersample=200)
    return w if descending else w[::-1, :]
