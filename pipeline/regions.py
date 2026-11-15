"""Pilot regions. One entry per region: where it is, which sources exist there, which
pipeline steps to run. Global NASA sources are shared; the local half differs by country.

Select a region with the FIELD_SHIFT_REGION environment variable or `--region` on
`python -m pipeline.run_all` / `python tasks.py data`.
"""
from __future__ import annotations

US_STEPS = ["fields", "power", "gridmet", "imerg", "smap", "ssurgo", "cdl", "landsat", "openet", "srtm",
            "modis", "nwis", "indicators", "overlays"]
INDIA_STEPS = ["blocks", "power", "srtm", "imd", "imerg", "smap", "soilgrids", "landsat", "wapor",
               "modis_pc", "grace", "indicators", "overlays"]

REGIONS: dict[str, dict] = {
    "diamond_valley_nv": {
        "id": "diamond_valley_nv",
        "name": "Diamond Valley, Eureka County, Nevada",
        "short": "Diamond Valley, Nevada",
        "country": "USA",
        "tagline": "Irrigated alfalfa under centre pivots, on falling groundwater",
        # west, south, east, north (WGS84). Core of the irrigated valley floor; kept under
        # 50,000 acres so one OpenET query covers it.
        "bbox": [-116.08, 39.62, -115.95, 39.75],
        "centroid": [-116.015, 39.685],
        "utm_epsg": 32611,
        "kb": "diamond_valley_nv",
        "field_unit": "pivot",
        "prefix": "DV",
        "steps": US_STEPS,
        "growing_months": [4, 5, 6, 7, 8, 9, 10],
        "hot_day_c": 32,
        "imperial": True,
        "has_frost": True,
        "landmark": "Eureka",
        "zoom": 11.6,
        # map layers: which months count as the green season, and which months bare soil matters
        "greenness_layers": [{"id": "ndvi", "title": "Summer greenness", "months": [6, 7, 8]}],
        "cover_months": [4, 5, 6, 7, 8, 9, 10],
    },
    "punjab_sangrur": {
        "id": "punjab_sangrur",
        "name": "Sangrur-Barnala, Punjab, India",
        "short": "Sangrur, Punjab",
        "country": "India",
        "tagline": "Rice-wheat on tubewells, where the water table drops every year",
        "bbox": [75.62, 30.22, 75.75, 30.35],
        "centroid": [75.685, 30.285],
        "utm_epsg": 32643,
        "kb": "punjab_sangrur",
        "field_unit": "block",
        "prefix": "PB",
        "steps": INDIA_STEPS,
        "growing_months": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
        "hot_day_c": 40,
        "imperial": False,
        "has_frost": False,
        "landmark": "Sangrur",
        "zoom": 11.6,
        "greenness_layers": [{"id": "ndvi", "title": "Monsoon-crop greenness (Aug-Sep)", "months": [8, 9]},
                             {"id": "ndvi_b", "title": "Winter-crop greenness (Feb-Mar)", "months": [2, 3]}],
        "cover_months": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
    },
    "cauvery_delta_tn": {
        "id": "cauvery_delta_tn",
        "name": "Cauvery delta, Thanjavur, Tamil Nadu, India",
        "short": "Cauvery delta, Tamil Nadu",
        "country": "India",
        "tagline": "Canal-fed paddy that waits on the Mettur dam and the north-east monsoon",
        "bbox": [79.20, 10.86, 79.33, 10.99],
        "centroid": [79.265, 10.925],
        "utm_epsg": 32644,
        "kb": "cauvery_delta_tn",
        "field_unit": "block",
        "prefix": "TN",
        "steps": INDIA_STEPS,
        "growing_months": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
        "hot_day_c": 38,
        "imperial": False,
        "has_frost": False,
        "landmark": "Thanjavur",
        "zoom": 11.6,
        "greenness_layers": [{"id": "ndvi", "title": "Kuruvai-season greenness (Jul-Sep)", "months": [7, 8, 9]},
                             {"id": "ndvi_b", "title": "Samba-season greenness (Dec-Feb)", "months": [12, 1, 2]}],
        "cover_months": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
    },
}

DEFAULT_REGION = "diamond_valley_nv"
