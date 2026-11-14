"""Run the whole data pipeline, one source after another.

    python -m pipeline.run_all            # everything
    python -m pipeline.run_all smap cdl   # only the named steps

A failing source is recorded (with the exact action needed) and the run continues:
nothing is fabricated to fill a gap. Every download is cached in data/raw, so a second
run only fetches what is missing.
"""
from __future__ import annotations

import importlib
import sys
import time

from .common import ensure_dirs, run_source

STEPS = [
    ("fields", "s00_fields"), ("power", "s01_power"), ("gridmet", "s11_gridmet"), ("imerg", "s02_imerg"),
    ("smap", "s03_smap"), ("ssurgo", "s04_ssurgo"), ("cdl", "s05_cdl"), ("landsat", "s06_landsat"),
    ("openet", "s07_openet"), ("srtm", "s08_srtm"), ("modis", "s09_modis"), ("nwis", "s10_nwis"),
    ("indicators", "s20_indicators"), ("overlays", "s30_overlays"), ("datalog", "data_log"),
]


def main(argv: list[str]) -> int:
    ensure_dirs()
    wanted = set(argv)
    unknown = wanted - {name for name, _ in STEPS}
    if unknown:
        print(f"Unknown step(s): {', '.join(sorted(unknown))}. Choose from: {', '.join(n for n, _ in STEPS)}")
        return 2
    failed = []
    for name, module in STEPS:
        if wanted and name not in wanted:
            continue
        mod = importlib.import_module(f"pipeline.{module}")
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
