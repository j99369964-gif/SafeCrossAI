"""Exports the small assets the Streamlit app needs, from files Notebook 2
already saved to disk. This script does not train or touch a model — it only
reads the saved intersection-week panel and writes a small demo CSV plus a
couple of deployment bookkeeping files.

Run from the REPOSITORY ROOT:

    python scripts/export_streamlit_assets.py

Requires pyarrow, since Notebook 2's panel is stored as Parquet.
"""

from __future__ import annotations

import json
import platform
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent

PANEL_PATH = REPO_ROOT / "data" / "processed" / "safecross_intersection_week_panel.parquet"
MODEL_METADATA_PATH = REPO_ROOT / "models" / "safecross_model_metadata.json"
DEMO_OUTPUT_PATH = REPO_ROOT / "data" / "sample" / "safecross_app_demo.csv"
VERSIONS_OUTPUT_PATH = REPO_ROOT / "deployment_versions.json"
REQUIREMENTS_OUTPUT_PATH = REPO_ROOT / "requirements.txt"

# If the demo CSV comes out too large for a snappy Streamlit Community Cloud
# deploy, lower this and re-run.
MAX_DEMO_ROWS = 5000

# Columns kept ON TOP OF whatever the model itself needs — for display,
# mapping, and identification, not for prediction. (node_id, latitude, and
# longitude are usually also in the model's own feature list, but are listed
# here too so they're always kept even if a future model formulation drops
# them as features.)
DISPLAY_ONLY_COLUMNS = [
    "node_id",
    "week_start",
    "latitude",
    "longitude",
    "intersection_label",
]


def main() -> None:
    if not PANEL_PATH.exists():
        sys.exit(
            f"Missing {PANEL_PATH}.\n"
            "Run Notebook 2 completely first — this script only reads its "
            "saved output, it does not build the panel itself."
        )

    if not MODEL_METADATA_PATH.exists():
        sys.exit(
            f"Missing {MODEL_METADATA_PATH}.\n"
            "Run Notebook 2 completely first — this script needs to know "
            "exactly which columns the trained model expects."
        )

    panel = pd.read_parquet(PANEL_PATH)

    with open(MODEL_METADATA_PATH, "r", encoding="utf-8") as file:
        metadata = json.load(file)

    # The model's OWN feature list is the source of truth for which columns
    # the demo CSV must contain — not a guessed prefix list. This is what
    # previously broke: weather columns are actually named things like
    # "current_week_mean_temperature_c", not "temperature_c", so a
    # startswith("temperature") guess silently dropped them, and predict_risk()
    # later raised a KeyError trying to select them.
    required_model_columns = metadata["numeric_features"] + metadata["categorical_features"]

    missing_from_panel = [column for column in required_model_columns if column not in panel.columns]
    if missing_from_panel:
        sys.exit(
            f"The saved panel is missing columns the model expects: {missing_from_panel}\n"
            "The panel and the model bundle were likely produced by different "
            "Notebook 2 runs. Re-run Notebook 2 fully so both are in sync, "
            "then re-run this script."
        )

    # Pick the single most recent COMPLETE week as the demo snapshot, so the
    # app has real, internally-consistent data to run predictions on without
    # shipping the entire historical panel.
    demo_week = panel["week_start"].max()
    demo_rows = panel.loc[panel["week_start"] == demo_week].copy()

    print(f"Selected demo week: {pd.Timestamp(demo_week).date()}")

    if len(demo_rows) > MAX_DEMO_ROWS:
        demo_rows = demo_rows.sample(n=MAX_DEMO_ROWS, random_state=42)

    columns_to_keep = [
        column for column in DISPLAY_ONLY_COLUMNS + required_model_columns if column in demo_rows.columns
    ]
    # De-duplicate while preserving order, in case a column appears in both
    # DISPLAY_ONLY_COLUMNS and required_model_columns.
    columns_to_keep = list(dict.fromkeys(columns_to_keep))

    demo_rows = demo_rows[columns_to_keep]

    DEMO_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    demo_rows.to_csv(DEMO_OUTPUT_PATH, index=False)

    print(f"Demo rows: {len(demo_rows):,}")
    print(f"Demo columns: {len(columns_to_keep)}")
    print(f"Saved: {DEMO_OUTPUT_PATH.relative_to(REPO_ROOT)}")

    # --- Deployment environment summary --------------------------------
    # A record of what produced this export, so a stale demo file is easy to
    # spot later (e.g. if pandas versions drift between training and deploy).
    versions = {
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "pandas_version": pd.__version__,
        "demo_week": str(pd.Timestamp(demo_week).date()),
        "demo_row_count": int(len(demo_rows)),
        "demo_column_count": len(columns_to_keep),
        "max_demo_rows": MAX_DEMO_ROWS,
        "selected_model": metadata.get("selected_model"),
    }
    with open(VERSIONS_OUTPUT_PATH, "w", encoding="utf-8") as file:
        json.dump(versions, file, indent=2)
    print(f"Saved: {VERSIONS_OUTPUT_PATH.relative_to(REPO_ROOT)}")

    # --- Deployment-compatible requirements.txt -------------------------
    # Regenerated here (rather than hand-maintained) so it reflects whatever
    # environment actually produced this export.
    deployment_requirements = [
        "pandas",
        "numpy",
        "scikit-learn",
        "xgboost",
        "lightgbm",
        "joblib",
        "streamlit",
        "streamlit-folium",
        "folium",
        "branca",
        "pyarrow",
    ]
    with open(REQUIREMENTS_OUTPUT_PATH, "w", encoding="utf-8") as file:
        file.write("\n".join(deployment_requirements) + "\n")
    print(f"Saved: {REQUIREMENTS_OUTPUT_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
