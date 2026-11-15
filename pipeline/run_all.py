"""Run the data pipeline for one region (or all), one source after another.

    python -m pipeline.run_all                               # default region, every step
    python -m pipeline.run_all --region punjab_sangrur       # one region
    python -m pipeline.run_all --region all                  # every region in turn
    python -m pipeline.run_all --region cauvery_delta_tn smap landsat   # only the named steps

A failing source is recorded (with the exact action needed) and the run continues:
nothing is fabricated to fill a gap. Every download is cached in data/raw/<region>, so a
second run only fetches what is missing.
"""
from __future__ import annotations

import importlib
import os
import subprocess
import sys
import time

# The region has to be chosen before pipeline.common is imported (it reads the variable).
if "--region" in sys.argv:
    _i = sys.argv.index("--region")
    os.environ["FIELD_SHIFT_REGION"] = sys.argv[_i + 1]
    del sys.argv[_i:_i + 2]

from .regions import REGIONS  # noqa: E402

MODULES = {
    "fields": "s00_fields", "blocks": "s00_blocks", "power": "s01_power", "gridmet": "s11_gridmet",
    "imd": "s11_imd", "imerg": "s02_imerg", "smap": "s03_smap", "ssurgo": "s04_ssurgo",
    "soilgrids": "s04_soilgrids", "cdl": "s05_cdl", "landsat": "s06_landsat", "openet": "s07_openet",
    "wapor": "s07_wapor", "srtm": "s08_srtm", "modis": "s09_modis", "modis_pc": "s09_modis_pc",
    "nwis": "s10_nwis", "grace": "s10_grace", "indicators": "s20_indicators", "overlays": "s30_overlays",
    "export": "s40_export", "datalog": "data_log",
}


def main(argv: list[str]) -> int:
    if os.environ.get("FIELD_SHIFT_REGION") == "all":
        code = 0
        for rid in REGIONS:
            print(f"\n================ {rid} ================", flush=True)
            env = {**os.environ, "FIELD_SHIFT_REGION": rid}
            code |= subprocess.run([sys.executable, "-m", "pipeline.run_all", *argv], env=env).returncode
        return code

    from .common import PILOT, ensure_dirs, run_source

    ensure_dirs()
    steps = argv or (PILOT["steps"] + ["export", "datalog"])
    unknown = [s for s in steps if s not in MODULES]
    if unknown:
        print(f"Unknown step(s): {', '.join(unknown)}. Steps for {PILOT['id']}: {', '.join(PILOT['steps'])}")
        return 2
    failed = []
    print(f"Region: {PILOT['name']}", flush=True)
    for name in steps:
        mod = importlib.import_module(f"pipeline.{MODULES[name]}")
        t0 = time.time()
        print(f"--- {name} ---", flush=True)
        ok = run_source(mod.SOURCE, mod.TITLE, mod.TIER, mod.main)
        print(f"    ({time.time() - t0:.0f} s)", flush=True)
        if not ok:
            failed.append(name)
    if failed:
        print(f"\nFinished with {len(failed)} source(s) needing attention: {', '.join(failed)}.")
        print("See DATA_LOG.md for the exact step each one needs. The app runs without them.")
    else:
        print("\nAll steps finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
