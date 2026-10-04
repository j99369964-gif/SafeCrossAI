"""Exports the small assets the Streamlit app needs, from files Notebook 2
already saved to disk. This script does not train or touch a model: it only
reads the saved model-ready table, keeps the most recent week for EVERY
intersection, and writes a demo CSV plus a deployment bookkeeping file.

Run from the REPOSITORY ROOT:

    python scripts/export_streamlit_assets.py

By default it reads Notebook 2's test-period predictions file
(data/processed/safecross_test_predictions.parquet). That file already holds
every intersection and every model feature for the test weeks, and it is
written in the same Notebook 2 run as the model, so the two can't be out of
sync. The full intersection-week panel is NOT needed (and at full-history,
citywide scale it would be many gigabytes). To read a panel file instead:

    python scripts/export_streamlit_assets.py --source panel

Requires pyarrow, since Notebook 2 stores these tables as Parquet.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent

SOURCE_PATHS = {
    "test_predictions": REPO_ROOT / "data" / "processed" / "safecross_test_predictions.parquet",
    "panel": REPO_ROOT / "data" / "processed" / "safecross_intersection_week_panel.parquet",
}
MODEL_METADATA_PATH = REPO_ROOT / "models" / "safecross_model_metadata.json"
DEMO_OUTPUT_PATH = REPO_ROOT / "data" / "sample" / "safecross_app_demo.csv"
VERSIONS_OUTPUT_PATH = REPO_ROOT / "deployment_versions.json"

# Keep EVERY intersection when possible. Random sampling is a last resort, because
# a sample both drops intersections and makes the app's relative risk tiers
# (which are percentiles among the rows loaded) describe the sample, not the city.
# Roughly 40,000 intersections fit comfortably: the CSV is on the order of
# 10-15 MB. Only if the export is larger than this is it sampled.
DEFAULT_MAX_DEMO_ROWS = 60_000

# If a single-borough export is accidentally produced, flag it. NYC spans about
# 0.43 degrees of latitude and 0.56 of longitude; Manhattan alone is roughly
# 0.2 x 0.1.
CITYWIDE_MIN_SPAN_DEGREES = 0.25

# Columns kept ON TOP OF whatever the model itself needs: for display,
# mapping, and identification, not for prediction.
DISPLAY_ONLY_COLUMNS = [
    "node_id",
    "week_start",
    "latitude",
    "longitude",
    "intersection_label",
]


def parquet_column_names(path: Path) -> list[str]:
    import pyarrow.parquet as pq

    return list(pq.read_schema(path).names)


def read_latest_week(path: Path, wanted_columns: list[str]) -> tuple[pd.Timestamp, pd.DataFrame]:
    """Reads ONLY the most recent week from a large Parquet file, and only the
    columns requested, so memory stays small even for tens of millions of rows."""
    available = parquet_column_names(path)
    columns = [column for column in wanted_columns if column in available]

    # Step 1: find the latest week by reading just that one column.
    latest_week = pd.read_parquet(path, columns=["week_start"])["week_start"].max()

    # Step 2: read only that week's rows. If the Parquet engine can't apply the
    # filter, fall back to reading the needed columns and filtering in pandas.
    try:
        frame = pd.read_parquet(path, columns=columns, filters=[("week_start", "==", latest_week)])
    except Exception:
        frame = pd.read_parquet(path, columns=columns)

    # Defensive: never trust that the engine applied the filter.
    frame = frame.loc[frame["week_start"] == latest_week].copy()
    return pd.Timestamp(latest_week), frame


def compact_numbers(frame: pd.DataFrame) -> pd.DataFrame:
    """Round floats so the CSV stays small. Six decimals is about 0.1 metre for
    coordinates, and float32 -> float64 conversion noise is removed first."""
    frame = frame.copy()
    for column in frame.columns:
        if pd.api.types.is_float_dtype(frame[column]):
            frame[column] = frame[column].astype("float64").round(6)
    return frame


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the Streamlit demo CSV.")
    parser.add_argument("--source", choices=sorted(SOURCE_PATHS), default="test_predictions")
    parser.add_argument("--max-rows", type=int, default=DEFAULT_MAX_DEMO_ROWS)
    args = parser.parse_args()

    source_path = SOURCE_PATHS[args.source]

    if not source_path.exists():
        sys.exit(
            f"Missing {source_path}.\n"
            "Run Notebook 2 completely first: this script only reads its saved output."
        )

    if not MODEL_METADATA_PATH.exists():
        sys.exit(
            f"Missing {MODEL_METADATA_PATH}.\n"
            "Run Notebook 2 completely first (and scripts/make_model_bundle.py): this script "
            "needs to know exactly which columns the trained model expects."
        )

    with open(MODEL_METADATA_PATH, "r", encoding="utf-8") as file:
        metadata = json.load(file)

    # The model's OWN feature list is the source of truth for which columns the
    # demo CSV must contain, not a guessed prefix list.
    required_model_columns = metadata["numeric_features"] + metadata["categorical_features"]

    available_columns = parquet_column_names(source_path)
    missing_from_source = [column for column in required_model_columns if column not in available_columns]
    if missing_from_source:
        sys.exit(
            f"{source_path.name} is missing columns the model expects: {missing_from_source}\n"
            "The data file and the model were likely produced by different "
            "Notebook 2 runs. Re-run Notebook 2 fully so both are in sync, "
            "then re-run scripts/make_model_bundle.py and this script."
        )

    wanted_columns = list(dict.fromkeys(DISPLAY_ONLY_COLUMNS + required_model_columns))
    demo_week, demo_rows = read_latest_week(source_path, wanted_columns)

    print(f"Source: {source_path.relative_to(REPO_ROOT)}")
    print(f"Selected demo week: {demo_week.date()}")

    # Guard against a stale file: the latest week in the data must be the last week
    # the model's own run reports. A mismatch means the files are from different runs.
    expected_last_week = metadata.get("test_end")
    if expected_last_week and pd.Timestamp(expected_last_week).date() != demo_week.date():
        sys.exit(
            f"Stale or mismatched data: the latest week in {source_path.name} is {demo_week.date()}, "
            f"but the model metadata says its run ended {expected_last_week}.\n"
            "Re-run Notebook 2 and scripts/make_model_bundle.py so every file comes from the same run."
        )

    n_intersections = int(demo_rows["node_id"].nunique())
    lat_span = float(demo_rows["latitude"].max() - demo_rows["latitude"].min())
    lon_span = float(demo_rows["longitude"].max() - demo_rows["longitude"].min())
    print(f"Intersections in the latest week: {n_intersections:,}")
    print(
        f"Latitude {demo_rows['latitude'].min():.3f} to {demo_rows['latitude'].max():.3f}, "
        f"longitude {demo_rows['longitude'].min():.3f} to {demo_rows['longitude'].max():.3f}"
    )
    if lat_span < CITYWIDE_MIN_SPAN_DEGREES and lon_span < CITYWIDE_MIN_SPAN_DEGREES:
        print(
            "WARNING: this covers a small area (roughly one borough or less). If you expected the "
            "whole city, the model and data were trained on a smaller scope: re-run Notebook 1 with "
            'BOROUGH = "ALL", then Notebook 2.'
        )

    if len(demo_rows) > args.max_rows:
        print(
            f"WARNING: {len(demo_rows):,} rows exceeds --max-rows ({args.max_rows:,}). Randomly sampling. "
            "The app's relative risk tiers will then describe the SAMPLE, not every intersection. "
            "Raise --max-rows if the deployment can handle a larger file."
        )
        demo_rows = demo_rows.sample(n=args.max_rows, random_state=42)

    columns_to_keep = [column for column in wanted_columns if column in demo_rows.columns]
    demo_rows = compact_numbers(demo_rows[columns_to_keep]).sort_values("node_id")

    DEMO_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    demo_rows.to_csv(DEMO_OUTPUT_PATH, index=False)

    size_mb = DEMO_OUTPUT_PATH.stat().st_size / 1e6
    print(f"Demo rows: {len(demo_rows):,}")
    print(f"Demo columns: {len(columns_to_keep)}")
    print(f"Saved: {DEMO_OUTPUT_PATH.relative_to(REPO_ROOT)} ({size_mb:.1f} MB)")
    if size_mb > 90:
        print("WARNING: over 90 MB. GitHub rejects files over 100 MB; lower --max-rows.")

    # --- Deployment environment summary --------------------------------
    versions = {
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "pandas_version": pd.__version__,
        "source": args.source,
        "demo_week": str(demo_week.date()),
        "demo_row_count": int(len(demo_rows)),
        "demo_intersection_count": n_intersections,
        "demo_column_count": len(columns_to_keep),
        "latitude_range": [round(float(demo_rows["latitude"].min()), 4), round(float(demo_rows["latitude"].max()), 4)],
        "longitude_range": [round(float(demo_rows["longitude"].min()), 4), round(float(demo_rows["longitude"].max()), 4)],
        "max_demo_rows": args.max_rows,
        "selected_model": metadata.get("selected_model"),
    }
    with open(VERSIONS_OUTPUT_PATH, "w", encoding="utf-8") as file:
        json.dump(versions, file, indent=2)
    print(f"Saved: {VERSIONS_OUTPUT_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
