"""Builds data/processed/historical_spatial_monthly.parquet: OBSERVED crash counts per H3 hexagon per month.

This feeds the app's "3D crash history" map. It is observed history only: nothing here uses or changes the model.

Why pre-aggregate: the raw NYC crash file has millions of rows. Sending them to the browser (or summing them on every
request) is slow, and drawing one marker per crash turns a multi-year map into an unreadable blob. Instead every
crash is assigned to one H3 hexagon and counted per month, so asking for "2021-2025" only sums a few hundred thousand
already-aggregated rows on the server, and the browser draws one column per hexagon.

Output columns:
    month                   first day of the month (YYYY-MM-01)
    h3_cell                 H3 cell id at H3_RESOLUTION
    crash_count             every crash with usable coordinates
    injury_crash_count      at least one person injured or killed
    pedestrian_crash_count  at least one pedestrian injured or killed
    cyclist_crash_count     at least one cyclist injured or killed
and a small companion file, historical_cells.parquet, with each cell's most common borough (for tooltips).

The NYC crash data only records pedestrians and cyclists when one of them is hurt, so the pedestrian and cyclist
counts are "crashes in which a pedestrian (cyclist) was injured or killed", not every crash they were involved in.

Run from the REPOSITORY ROOT:

    python scripts/build_historical_density.py

Needs the h3 package (pip install "h3>=4,<5") and pyarrow. Only this script needs h3; the server and browser read
the cell ids as they are.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw"
OUTPUT_DIR = REPO_ROOT / "data" / "processed"
OUTPUT_PATH = OUTPUT_DIR / "historical_spatial_monthly.parquet"
CELLS_PATH = OUTPUT_DIR / "historical_cells.parquet"

# H3 resolution 9: hexagons about 175 m across an edge (~0.1 km2), a few blocks in Manhattan. Coarse enough that
# 15 years of crashes form readable columns, fine enough to tell one avenue corridor from the next.
H3_RESOLUTION = 9

# Rows outside this box have missing or junk coordinates (the raw file uses 0,0 and a few far-off points).
NYC_BOX = {"south": 40.45, "north": 40.95, "west": -74.30, "east": -73.65}

COLUMNS = [
    "crash_date", "latitude", "longitude", "borough",
    "number_of_persons_injured", "number_of_persons_killed",
    "number_of_pedestrians_injured", "number_of_pedestrians_killed",
    "number_of_cyclist_injured", "number_of_cyclist_killed",
]


def find_raw_file(raw_dir: Path) -> Path:
    candidates = sorted(raw_dir.glob("nyc_crashes_*.csv"))
    if not candidates:
        sys.exit(f"No nyc_crashes_*.csv in {raw_dir}. Run Notebook 1 first.")
    return candidates[-1]


def load_crashes(path: Path) -> pd.DataFrame:
    print(f"Reading {path.relative_to(REPO_ROOT)} ...")
    frame = pd.read_csv(path, usecols=COLUMNS, dtype={"borough": "string"}, low_memory=False)
    total = len(frame)
    frame["latitude"] = pd.to_numeric(frame["latitude"], errors="coerce")
    frame["longitude"] = pd.to_numeric(frame["longitude"], errors="coerce")
    inside = (
        frame["latitude"].between(NYC_BOX["south"], NYC_BOX["north"])
        & frame["longitude"].between(NYC_BOX["west"], NYC_BOX["east"])
    )
    frame = frame.loc[inside].copy()
    frame["month"] = pd.to_datetime(frame["crash_date"], errors="coerce").dt.to_period("M").dt.to_timestamp()
    frame = frame.loc[frame["month"].notna()]
    print(f"  {total:,} crashes, {len(frame):,} with usable coordinates and dates ({len(frame) / total:.0%})")
    return frame


def count_columns(frame: pd.DataFrame) -> pd.DataFrame:
    def hurt(*columns: str) -> pd.Series:
        return sum(pd.to_numeric(frame[c], errors="coerce").fillna(0) for c in columns) > 0

    return pd.DataFrame(
        {
            "crash_count": 1,
            "injury_crash_count": hurt("number_of_persons_injured", "number_of_persons_killed").astype(int),
            "pedestrian_crash_count": hurt("number_of_pedestrians_injured", "number_of_pedestrians_killed").astype(int),
            "cyclist_crash_count": hurt("number_of_cyclist_injured", "number_of_cyclist_killed").astype(int),
        },
        index=frame.index,
    )


def assign_cells(frame: pd.DataFrame, resolution: int) -> pd.Series:
    """H3 cell per crash. Many crashes share exact coordinates, so each distinct point is converted once."""
    import h3

    points = frame[["latitude", "longitude"]].drop_duplicates()
    cells = [h3.latlng_to_cell(lat, lng, resolution) for lat, lng in points.itertuples(index=False)]
    lookup = pd.Series(cells, index=pd.MultiIndex.from_frame(points))
    print(f"  {len(points):,} distinct crash locations -> {lookup.nunique():,} H3 cells (resolution {resolution})")
    return pd.Series(lookup.reindex(pd.MultiIndex.from_frame(frame[["latitude", "longitude"]])).to_numpy(), index=frame.index)


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate observed NYC crashes into monthly H3 hexagon counts.")
    parser.add_argument("--raw", type=Path, default=None, help="crash CSV (default: newest data/raw/nyc_crashes_*.csv)")
    parser.add_argument("--resolution", type=int, default=H3_RESOLUTION)
    args = parser.parse_args()

    crashes = load_crashes(args.raw or find_raw_file(RAW_DIR))
    counts = count_columns(crashes)
    counts["month"] = crashes["month"]
    counts["h3_cell"] = assign_cells(crashes, args.resolution)

    monthly = counts.groupby(["month", "h3_cell"], as_index=False, sort=True).sum()
    for column in ("crash_count", "injury_crash_count", "pedestrian_crash_count", "cyclist_crash_count"):
        monthly[column] = monthly[column].astype(np.int32)

    # Most common borough per cell, for tooltips. Many raw rows leave borough blank, so blanks are ignored.
    boroughs = crashes["borough"].str.strip().str.title().replace("", pd.NA)
    named = pd.DataFrame({"h3_cell": counts["h3_cell"], "borough": boroughs}).dropna()
    cells = named.groupby("h3_cell")["borough"].agg(lambda s: s.mode().iat[0]).reset_index()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    monthly.to_parquet(OUTPUT_PATH, index=False)
    cells.to_parquet(CELLS_PATH, index=False)
    first, last = monthly["month"].min(), monthly["month"].max()
    print(
        f"\nSaved: {OUTPUT_PATH.relative_to(REPO_ROOT)} ({OUTPUT_PATH.stat().st_size / 1e6:.1f} MB, {len(monthly):,} rows, "
        f"{monthly['h3_cell'].nunique():,} cells, {first:%Y-%m} to {last:%Y-%m}, {int(monthly['crash_count'].sum()):,} crashes)"
    )
    print(f"Saved: {CELLS_PATH.relative_to(REPO_ROOT)} ({len(cells):,} cells with a borough)")


if __name__ == "__main__":
    main()
