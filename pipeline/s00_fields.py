"""Pilot field boundaries.

OpenET's field-boundary endpoint rejected every request when this pipeline was built
(HTTP 400 "Invalid geometry", even for the example in its own documentation), so the
boundaries are **detected from Landsat** instead:

1. peak-summer greenness: for each of the last three summers take the 90th percentile of
   clear-sky NDVI (1 Jun - 31 Aug), then the maximum across the summers (so a pivot that
   was fallow or in a thin crop in one or two years is still found);
2. irrigated land = peak NDVI >= 0.45 (the surrounding desert shrub stays below ~0.3);
3. centre pivots are circles that touch their neighbours, so blobs cannot simply be
   labelled. Instead take the distance from every irrigated pixel to the nearest
   non-irrigated pixel: its local maxima are the pivot centres and its value there is the
   pivot radius (the largest circle that fits inside the irrigated footprint);
4. keep circles of 250-480 m radius (20-72 ha) that sit fully inside the pilot box, and
   drop any circle that overlaps a larger one.

The pilot set is then chosen for variety of crop history (from the USDA CDL) and spread
across the valley. These are satellite-derived outlines, not surveyed boundaries, and the
app says so; a farmer can always draw their own field instead.

Outputs: data/processed/fields.geojson, data/processed/fields_context.geojson
"""
from __future__ import annotations

import json
import math

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy import ndimage

from .common import PILOT, PROCESSED, SourceError, run_source, write_status
from .s05_cdl import download_all, field_fractions
from .s06_landsat import cached_keys, fetch_scenes, load_scene, target_grid

SOURCE, TITLE, TIER = "fields", "Pilot field boundaries (detected from Landsat)", "MUST"
DETECT_YEARS = (2023, 2024, 2025)
PEAK_THRESHOLD = 0.45
MIN_RADIUS_M, MAX_RADIUS_M = 250.0, 480.0
N_FIELDS = 14
HISTORY_YEARS = list(range(2018, 2026))


def peak_summer_ndvi() -> tuple[np.ndarray, dict]:
    """Maximum over summers of each summer's 90th-percentile clear-sky NDVI."""
    _, shape, _ = target_grid()
    per_year, used = [], {}
    for year in DETECT_YEARS:
        fetch_scenes(f"{year}-06-01", f"{year}-08-31")
        arrs = []
        for key in cached_keys(f"{year}-06-01", f"{year}-08-31"):
            z = load_scene(key)
            if z is None:
                continue
            arrs.append(np.where(z["flags"] == 1, z["ndvi"] / 10000.0, np.nan).astype("float32"))
        used[year] = len(arrs)
        if len(arrs) < 3:
            continue
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            per_year.append(np.nanpercentile(np.stack(arrs), 90, axis=0))
    if len(per_year) < 2:
        raise SourceError("Not enough clear summer Landsat scenes to detect fields",
                          action="Run `python -m pipeline.s06_landsat` first (needs internet).")
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        peak = np.nanmax(np.stack(per_year), axis=0)
    return peak, used


def detect(peak: np.ndarray) -> gpd.GeoDataFrame:
    """Fit the largest inscribed circle to every pivot in the irrigated mask."""
    from shapely.geometry import Point

    transform, shape, _ = target_grid()
    mask = np.nan_to_num(peak, nan=0.0) >= PEAK_THRESHOLD
    mask = ndimage.binary_opening(mask, structure=np.ones((3, 3), bool))
    # fill only small holes (pivot-centre pads, wheel tracks); the star-shaped gaps between
    # four touching pivots must stay open or the circles would merge into one block
    holes, nh = ndimage.label(~mask)
    sizes = ndimage.sum(~mask, holes, range(1, nh + 1))
    small = np.isin(holes, [i + 1 for i, sz in enumerate(sizes) if sz <= 12])
    mask = mask | small
    dist = ndimage.distance_transform_edt(mask)     # pixels to the nearest non-irrigated pixel
    smooth = ndimage.gaussian_filter(dist, 1.0)
    peaks = (ndimage.maximum_filter(smooth, size=15) == smooth) & (dist * 30 >= MIN_RADIUS_M)
    lab, n = ndimage.label(peaks)
    found = []
    for i, (r, c) in enumerate(ndimage.center_of_mass(peaks, lab, range(1, n + 1))):
        rad_m = float(dist[int(round(r)), int(round(c))]) * 30.0
        if not (MIN_RADIUS_M <= rad_m <= MAX_RADIUS_M):
            continue
        x, y = transform * (c + 0.5, r + 0.5)
        found.append((rad_m, x, y))
    found.sort(reverse=True)                         # largest first, then drop overlaps
    kept: list[tuple[float, float, float]] = []
    for rad, x, y in found:
        if all(math.hypot(x - kx, y - ky) >= 0.9 * (rad + kr) for kr, kx, ky in kept):
            kept.append((rad, x, y))
    h, w = shape
    x0, y1 = transform.c, transform.f
    x1, y0 = x0 + w * 30, y1 - h * 30
    recs = []
    for rad, x, y in kept:
        if x - rad < x0 + 60 or x + rad > x1 - 60 or y - rad < y0 + 60 or y + rad > y1 - 60:
            continue
        recs.append({"radius_m": round(rad, 1), "geometry": Point(x, y).buffer(rad, 48)})
    gdf = gpd.GeoDataFrame(recs, crs=f"EPSG:{PILOT['utm_epsg']}")
    gdf["area_ha"] = gdf.geometry.area / 1e4
    gdf["compactness"] = 4 * math.pi * gdf.geometry.area / gdf.geometry.length ** 2
    gdf["field_id"] = [f"C{i:03d}" for i in range(len(gdf))]
    return gdf


def crop_history(cands: gpd.GeoDataFrame) -> pd.DataFrame:
    paths, _, _, _ = download_all()
    paths = {y: p for y, p in paths.items() if y in HISTORY_YEARS}
    return field_fractions(cands.to_crs(4326), paths)


def choose(cands: gpd.GeoDataFrame, hist: pd.DataFrame) -> gpd.GeoDataFrame:
    """Pick N_FIELDS for variety of crop history and spread across the valley (deterministic)."""
    piv = hist.pivot(index="field_id", columns="year", values="cdl_code")
    alfalfa_years = (piv == 36).sum(axis=1)
    cands = cands.set_index("field_id")
    cands["alfalfa_years"] = alfalfa_years
    cands["n_crops"] = piv.apply(lambda r: r.dropna().nunique(), axis=1)
    cands = cands.dropna(subset=["alfalfa_years"])
    n_hist = piv.shape[1]
    cat = np.where(cands["alfalfa_years"] >= n_hist - 1, "A",
                   np.where(cands["alfalfa_years"] >= n_hist // 2, "B", "C"))
    cands["category"] = cat
    cx, cy = cands.geometry.centroid.x, cands.geometry.centroid.y
    centre = (cx.mean(), cy.mean())

    def pick(pool: pd.Index, k: int, chosen: list[str]) -> list[str]:
        pool = [p for p in pool if p not in chosen]
        out: list[str] = []
        while pool and len(out) < k:
            ref = chosen + out
            if not ref:
                d = [(cx[p] - centre[0]) ** 2 + (cy[p] - centre[1]) ** 2 for p in pool]
                best = pool[int(np.argmin(d))]
            else:
                d = [min((cx[p] - cx[r]) ** 2 + (cy[p] - cy[r]) ** 2 for r in ref) for p in pool]
                best = pool[int(np.argmax(d))]
            out.append(best)
            pool.remove(best)
        return out

    classic = cands[cands["area_ha"].between(35, 75)]      # full quarter-section pivots
    chosen: list[str] = []
    for c, k in (("A", 8), ("B", 4), ("C", 2)):
        pool = classic.index[classic["category"] == c]
        got = pick(pool, k, chosen)
        if len(got) < k:   # not enough classic pivots in this category: relax the shape rule
            got += pick(cands.index[cands["category"] == c], k - len(got), chosen + got)
        chosen += got
    if len(chosen) < N_FIELDS:
        chosen += pick(classic.index, N_FIELDS - len(chosen), chosen)
    sel = cands.loc[chosen].copy()
    cen = gpd.GeoSeries(sel.geometry.centroid, crs=sel.crs).to_crs(4326)
    sel["lat"], sel["lon"] = cen.y.values, cen.x.values
    sel = sel.sort_values(["lat", "lon"], ascending=[False, True]).reset_index()
    sel["old_id"] = sel["field_id"]
    sel["field_id"] = [f"DV-{i + 1:02d}" for i in range(len(sel))]
    sel["name"] = [f"Field {i + 1}" for i in range(len(sel))]
    return sel


def main() -> None:
    peak, used = peak_summer_ndvi()
    cands = detect(peak)
    if len(cands) < 8:
        raise SourceError(f"Only {len(cands)} field-like shapes detected in the pilot box")
    hist = crop_history(cands)
    sel = choose(cands, hist)

    sel["shape_type"] = np.where(sel["area_ha"] >= 35, "centre-pivot circle",
                                 "small or partial pivot (largest circle that fits)")
    sel["history_group"] = sel["category"].map({
        "A": "long-stand alfalfa", "B": "alfalfa with breaks", "C": "mostly other crops"})
    out = sel.to_crs(4326)[["field_id", "name", "area_ha", "radius_m", "shape_type", "lon", "lat",
                             "alfalfa_years", "history_group", "geometry"]].copy()
    out["area_ha"] = out["area_ha"].round(1)
    out["area_acres"] = (out["area_ha"] * 2.47105).round(0)
    out["lon"], out["lat"] = out["lon"].round(5), out["lat"].round(5)
    out["alfalfa_years"] = out["alfalfa_years"].astype(int)
    out["boundary_source"] = ("Detected from Landsat 8/9 peak-summer NDVI "
                              f"{DETECT_YEARS[0]}-{DETECT_YEARS[-1]}; not a surveyed boundary")
    out["is_demo_data"] = False
    out.to_file(PROCESSED / "fields.geojson", driver="GeoJSON")

    ctx = cands[~cands["field_id"].isin(sel["old_id"])].to_crs(4326)[["area_ha", "geometry"]].copy()
    ctx["area_ha"] = ctx["area_ha"].round(1)
    ctx.to_file(PROCESSED / "fields_context.geojson", driver="GeoJSON")

    groups = out["history_group"].value_counts().to_dict()
    ok = len(out) == N_FIELDS and out["area_ha"].between(19, 75).all()
    write_status(
        SOURCE, status="ok" if ok else "partial", title=TITLE, tier=TIER,
        fetched=f"{len(cands)} field-like irrigated shapes detected in the pilot box; {len(out)} chosen "
                f"as pilot fields ({json.dumps(groups)})",
        resolution="30 m (Landsat); each field is the largest circle inside its irrigated footprint",
        date_range=f"summers {DETECT_YEARS[0]}-{DETECT_YEARS[-1]} "
                   f"(clear scenes used per summer: {json.dumps(used)})",
        credit="Derived by this project from Landsat 8/9 Collection 2 Level-2 (USGS/NASA) and the "
               "USDA NASS Cropland Data Layer.",
        access="pipeline/s00_fields.py (see docstring for the method)",
        message=f"{len(out)} pilot fields, {out['area_ha'].min():.0f}-{out['area_ha'].max():.0f} ha, "
                f"median radius {out['radius_m'].median():.0f} m",
        sanity={"crs": "EPSG:4326", "n_candidates": int(len(cands)),
                "area_ha_range": [float(out["area_ha"].min()), float(out["area_ha"].max())],
                "all_inside_pilot_box": True, "passed": bool(ok)},
        outputs=["fields.geojson", "fields_context.geojson"],
        notes="OpenET's /geodatabase/metadata/ids endpoint returned HTTP 400 'Invalid geometry' for "
              "every request, including the example in its own documentation, so OpenET's field "
              "boundaries could not be used. Boundaries here are satellite-derived approximations.",
    )


if __name__ == "__main__":
    run_source(SOURCE, TITLE, TIER, main)
