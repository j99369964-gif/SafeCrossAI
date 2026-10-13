"""Shared utilities for the SafeCross AI Streamlit app.

Everything in this module only READS files that Notebook 2, Notebook 3, and
scripts/export_streamlit_assets.py already wrote to disk. Nothing here trains
or fits a model.
"""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import streamlit as st

# The pure scoring / presentation logic lives in safecross_core.py (no Streamlit import), so the PWA's API
# server can use exactly the same code. It is re-exported here so existing imports from app_utils keep working.
from safecross_core import (  # noqa: F401
    FALLBACK_SIGNAL_FEATURES,
    NON_SIGNAL_FEATURES,
    NON_SIGNAL_PREFIXES,
    REGION_META,
    TRANSFER_BLANKED_FEATURES,
    add_intersection_labels,
    merge_intersection_info,
    assign_risk_tier,
    build_risk_grid,
    candidate_measures_for_row,
    force_cpu_for_deployment,
    format_intersection_label,
    is_intersection_signal,
    predict_risk,
    same_region_rows,
    score_region,
    top_signals_for_row,
    unvalidated_note,
)

# --- Project paths ----------------------------------------------------
# app_utils.py lives in app/, so the repo root is one level up.
REPO_ROOT = Path(__file__).resolve().parent.parent

MODEL_BUNDLE_PATH = REPO_ROOT / "models" / "safecross_model_bundle.joblib"
MODEL_METADATA_PATH = REPO_ROOT / "models" / "safecross_model_metadata.json"
DEMO_DATA_PATH = REPO_ROOT / "data" / "sample" / "safecross_app_demo.csv"
TEST_METRICS_PATH = REPO_ROOT / "reports" / "metrics" / "selected_model_test_metrics.json"
IMPORTANCE_PATH = REPO_ROOT / "reports" / "notebook_02_03" / "permutation_importance.csv"







# --- Regions ----------------------------------------------------------------
# "nyc" is the area the model was trained AND validated on. Every other region is a TRANSFER region:
# the same NYC-trained model applied to roads it never saw crash data for. For those rows
#   * crash-history features and latitude/longitude are blanked before scoring (they have no crash
#     history, and Westchester lies north of every location the model trained on), so the model's own
#     imputer treats them as "typical" and the ranking comes from road design alone;
#   * risk tiers and percentiles are computed WITHIN the region. Scores built from different information
#     (NYC: with crash history; Westchester: road design only) cannot be ranked against each other;
#   * everything shown to the user is labelled "unvalidated".
DEMO_DATA_PATH_WESTCHESTER = REPO_ROOT / "data" / "sample" / "safecross_app_demo_westchester.csv"
# Street names, sidewalk, bike lane, lighting... written by scripts/build_intersection_info.py (optional).
# Height of one area-view square in degrees of latitude (0.005 is about 550 m). Smaller = finer detail, more squares.
GRID_CELL_DEGREES = 0.005
INTERSECTION_INFO_PATH = REPO_ROOT / "data" / "sample" / "intersection_info.csv"

REGIONS = {
    key: {**meta, "path": DEMO_DATA_PATH if key == "nyc" else DEMO_DATA_PATH_WESTCHESTER}
    for key, meta in REGION_META.items()
}





# --- Cached loaders ------------------------------------------------------
@st.cache_resource(show_spinner="Loading model...")
def load_model_bundle() -> dict:
    """Load the frozen model bundle Notebook 2 saved. Cached for the life of
    the app process, since the bundle never changes without a redeploy."""
    if not MODEL_BUNDLE_PATH.exists():
        raise FileNotFoundError(
            f"Missing {MODEL_BUNDLE_PATH}. Run Notebook 2 and commit "
            "models/safecross_model_bundle.joblib to the repository."
        )
    bundle = joblib.load(MODEL_BUNDLE_PATH)
    force_cpu_for_deployment(bundle["model"])
    return bundle




@st.cache_data(show_spinner=False)
def load_metadata() -> dict:
    if not MODEL_METADATA_PATH.exists():
        raise FileNotFoundError(f"Missing {MODEL_METADATA_PATH}.")
    with open(MODEL_METADATA_PATH, "r", encoding="utf-8") as file:
        return json.load(file)


@st.cache_data(show_spinner="Loading demo data...")
def load_demo_data() -> pd.DataFrame:
    if not DEMO_DATA_PATH.exists():
        raise FileNotFoundError(
            f"Missing {DEMO_DATA_PATH}. Run "
            "`python scripts/export_streamlit_assets.py` from the repository "
            "root first."
        )
    return pd.read_csv(DEMO_DATA_PATH)


@st.cache_data(show_spinner=False)
def load_test_metrics() -> dict | None:
    """Optional — the app still works without this, just with a less
    detailed "Model" tab."""
    if not TEST_METRICS_PATH.exists():
        return None
    with open(TEST_METRICS_PATH, "r", encoding="utf-8") as file:
        return json.load(file)


@st.cache_data(show_spinner=False)
def load_signal_features(numeric_features: list[str]) -> list[str]:
    """Ranks candidate "signal" features by global permutation importance if
    that file was exported from Notebook 3; otherwise falls back to a fixed,
    documented ordering so the app still works with a minimal file set."""
    if IMPORTANCE_PATH.exists():
        importance_table = pd.read_csv(IMPORTANCE_PATH)
        ranked = [
            feature
            for feature in importance_table["feature"].tolist()
            if feature in numeric_features and is_intersection_signal(feature)
        ]
        if ranked:
            return ranked[:8]

    return [
        feature
        for feature in FALLBACK_SIGNAL_FEATURES
        if feature in numeric_features and is_intersection_signal(feature)
    ]










@st.cache_data(show_spinner="Scoring intersections...")
def load_scored_demo_data() -> pd.DataFrame:
    """Loads the demo rows and scores them ONCE (cached). Streamlit re-runs the
    whole script on every pan/zoom/click, so inference must not live in the
    top-level script body: with ~40,000 citywide intersections it would be
    repeated on every interaction."""
    bundle = load_model_bundle()
    parts = [score_region(bundle, load_demo_data(), "nyc")]
    # Transfer regions are optional: the app works with only the NYC file.
    for region_key, region in REGIONS.items():
        if region_key != "nyc" and region["path"].exists():
            parts.append(score_region(bundle, pd.read_csv(region["path"]), region_key))
    info = pd.read_csv(INTERSECTION_INFO_PATH, dtype={"node_id": str}) if INTERSECTION_INFO_PATH.exists() else None
    return add_intersection_labels(merge_intersection_info(pd.concat(parts, ignore_index=True), info))












@st.cache_data(show_spinner=False)
def cached_risk_grid(rows: pd.DataFrame) -> dict:
    """build_risk_grid, cached. Pass only the columns it needs
    (latitude, longitude, predicted_probability, risk_tier) so hashing is cheap."""
    return build_risk_grid(rows, cell_size=GRID_CELL_DEGREES)
