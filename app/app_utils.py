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

# --- Project paths ----------------------------------------------------
# app_utils.py lives in app/, so the repo root is one level up.
REPO_ROOT = Path(__file__).resolve().parent.parent

MODEL_BUNDLE_PATH = REPO_ROOT / "models" / "safecross_model_bundle.joblib"
MODEL_METADATA_PATH = REPO_ROOT / "models" / "safecross_model_metadata.json"
DEMO_DATA_PATH = REPO_ROOT / "data" / "sample" / "safecross_app_demo.csv"
TEST_METRICS_PATH = REPO_ROOT / "reports" / "metrics" / "selected_model_test_metrics.json"
IMPORTANCE_PATH = REPO_ROOT / "reports" / "notebook_02_03" / "permutation_importance.csv"

# A small, documented fallback list used to rank "top model signals" only if
# the optional permutation_importance.csv isn't present in this deployment.
# Ordered by what Notebook 2's ablation results showed mattered most: recent
# crash history first, then road-design context.
FALLBACK_SIGNAL_FEATURES = [
    "crashes_last_4w",
    "crashes_last_8w",
    "weeks_since_last_crash",
    "max_connecting_speed_limit",
    "street_count",
    "max_connecting_lanes",
    "touches_oneway_street",
    "is_traffic_signal",
]


# Features that describe WHERE or WHEN a row is rather than the intersection itself.
# Weather and season are identical for every intersection in a given week, and
# coordinates are only a location proxy, so none of them can explain why one
# intersection ranks above another. They are skipped when picking "top signals".
NON_SIGNAL_FEATURES = {"latitude", "longitude"}
NON_SIGNAL_PREFIXES = ("current_week_", "week_of_year")


def is_intersection_signal(feature: str) -> bool:
    return feature not in NON_SIGNAL_FEATURES and not feature.startswith(NON_SIGNAL_PREFIXES)


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


def force_cpu_for_deployment(model) -> None:
    """Notebook 2 may train XGBoost with device="cuda" on a Colab GPU. This
    deployment (Streamlit Community Cloud) has no GPU, so inference must run
    on CPU. This does NOT retrain the model — it only changes where the
    already-fitted booster runs predictions. Safely does nothing for models
    that don't have these XGBoost-specific methods (logistic regression,
    LightGBM, MLP, random forest)."""
    if hasattr(model, "set_params"):
        try:
            model.set_params(device="cpu")
        except (ValueError, TypeError):
            # Not every estimator recognizes a "device" parameter — that's
            # fine, it just means this isn't the GPU-capable XGBoost model.
            pass

    if hasattr(model, "get_booster"):
        try:
            model.get_booster().set_param({"device": "cpu"})
        except Exception:
            pass


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


# --- Prediction and presentation -----------------------------------------
def predict_risk(bundle: dict, rows: pd.DataFrame) -> np.ndarray:
    """Runs the frozen preprocessor + model on raw feature rows and returns
    predicted probabilities. This is the ONLY place inference happens."""
    raw_features = bundle["raw_features"]
    transformed = bundle["preprocessor"].transform(rows[raw_features])
    return bundle["model"].predict_proba(transformed)[:, 1]


def add_intersection_labels(frame: pd.DataFrame) -> pd.DataFrame:
    """Adds a human-readable intersection_label to every row at once (vectorized).
    Uses the exported intersection_label column where present, otherwise
    falls back to node id + coordinates. Replaces a row-by-row .apply(), which
    is far too slow to repeat on every interaction once there are tens of
    thousands of intersections."""
    frame = frame.copy()
    fallback = (
        "OSM node " + frame["node_id"].astype(str)
        + " | " + frame["latitude"].map("{:.4f}".format)
        + ", " + frame["longitude"].map("{:.4f}".format)
    )
    if "intersection_label" in frame.columns:
        frame["intersection_label"] = frame["intersection_label"].where(frame["intersection_label"].notna(), fallback).astype(str)
    else:
        frame["intersection_label"] = fallback
    return frame


@st.cache_data(show_spinner="Scoring intersections...")
def load_scored_demo_data() -> pd.DataFrame:
    """Loads the demo rows and scores them ONCE (cached). Streamlit re-runs the
    whole script on every pan/zoom/click, so inference must not live in the
    top-level script body: with ~40,000 citywide intersections it would be
    repeated on every interaction."""
    bundle = load_model_bundle()
    data = load_demo_data().copy()
    data["predicted_probability"] = predict_risk(bundle, data)
    data["risk_tier"] = assign_risk_tier(data["predicted_probability"])
    data["risk_percentile"] = data["predicted_probability"].rank(pct=True) * 100
    return add_intersection_labels(data)


def assign_risk_tier(probability: pd.Series) -> pd.Series:
    """Converts probabilities into a RELATIVE risk tier — ranked against the
    other rows currently loaded, not a literal "X% chance of a crash".
    Calibration is weak enough that presenting raw probabilities as literal
    odds would overstate precision (see Notebook 2's guardrails)."""
    percentile = probability.rank(pct=True) * 100

    conditions = [percentile >= 90, percentile >= 75, percentile >= 50]
    labels = ["Highest-priority (top 10%)", "Elevated relative risk", "Moderate relative risk"]

    return pd.Series(np.select(conditions, labels, default="Lower relative risk"), index=probability.index)


def top_signals_for_row(
    row: pd.Series,
    signal_features: list[str],
    top_n: int = 3,
    reference: pd.DataFrame | None = None,
    min_percentile: float = 0.5,
) -> list[tuple[str, float, float | None]]:
    """Simple, explainable approximation of "what likely drove this row's
    ranking": the top_n candidate signal features whose values are most
    unusually HIGH for this row. Returns (feature, value, percentile) triples,
    where percentile is the share of rows in `reference` with a strictly lower
    value. Ranking by percentile rather than raw value matters because features
    are in different units (a crash count of 2 vs. a 35 mph speed limit). Not a
    per-row attribution method (e.g. SHAP): good enough to point a reviewer
    toward likely drivers, not proof of causation.

    When `reference` is given, only features at or above `min_percentile` (default:
    the median) are returned, so a value that is LOW for this intersection is
    never presented as a "signal". An intersection with none returns an empty list."""
    scored = []
    for feature in signal_features:
        if feature not in row or pd.isna(row[feature]):
            continue
        try:
            value = float(row[feature])
        except (TypeError, ValueError):
            continue  # text features can't be ranked this way
        percentile = None
        if reference is not None and feature in reference.columns:
            percentile = float((reference[feature] < value).mean())
        scored.append((feature, value, percentile))

    if reference is not None:
        scored = [item for item in scored if item[2] is not None and item[2] >= min_percentile]
        scored.sort(key=lambda item: (item[2] is not None, item[2] or 0.0, item[1]), reverse=True)
    else:
        scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:top_n]


def candidate_measures_for_row(row: pd.Series) -> list[str]:
    """Simple, transparent rule-based suggestions for further review — never
    a model output and never a final recommendation. Mirrors the same rules
    used in Notebook 3 so the app and the notebook tell a consistent story."""
    measures = []

    if row.get("pedestrian_casualty_crashes_last_8w", 0) and row["pedestrian_casualty_crashes_last_8w"] > 0:
        measures.append("Review crosswalk marking/visibility")

    if row.get("cyclist_casualty_crashes_last_8w", 0) and row["cyclist_casualty_crashes_last_8w"] > 0:
        measures.append("Review bike-lane/intersection conflict design")

    max_speed = row.get("max_connecting_speed_limit")
    if max_speed is not None and pd.notna(max_speed) and max_speed >= 35:
        measures.append("Review traffic-calming / speed-limit appropriateness")

    if row.get("is_traffic_signal", 0) == 0 and row.get("street_count", 0) and row["street_count"] >= 4:
        measures.append("Review whether signal or stop control is warranted")

    if not measures:
        measures.append("No rule-based candidate measure triggered — recommend manual site review")

    return measures


def build_risk_grid(rows: pd.DataFrame, target_bins: int = 30) -> dict:
    """Aggregates point-level rows into a grid of square cells, returned as a
    GeoJSON FeatureCollection with each cell\'s mean predicted probability,
    dominant risk tier, and point count baked into its properties. Used to
    render a choropleth-style overview before zooming in to individual
    intersection markers — showing thousands of overlapping circle markers
    at a city-wide zoom level is unreadable, whereas an area-level color
    gives a usable overview at that scale.

    Pure-Python/pandas — no geopandas/shapely dependency, since the cells
    are simple axis-aligned rectangles, not real geometry operations."""
    if rows.empty or not {"latitude", "longitude", "predicted_probability"}.issubset(rows.columns):
        return {"type": "FeatureCollection", "features": []}

    lat_span = max(rows["latitude"].max() - rows["latitude"].min(), 1e-6)
    lon_span = max(rows["longitude"].max() - rows["longitude"].min(), 1e-6)
    cell_size = max(lat_span, lon_span) / target_bins

    grid_rows = rows.copy()
    grid_rows["cell_lat"] = (grid_rows["latitude"] // cell_size) * cell_size
    grid_rows["cell_lon"] = (grid_rows["longitude"] // cell_size) * cell_size

    cell_groups = grid_rows.groupby(["cell_lat", "cell_lon"])

    features = []
    for (cell_lat, cell_lon), cell_points in cell_groups:
        mean_probability = float(cell_points["predicted_probability"].mean())
        dominant_tier = cell_points["risk_tier"].mode().iat[0] if "risk_tier" in cell_points else None

        polygon = [
            [
                [cell_lon, cell_lat],
                [cell_lon + cell_size, cell_lat],
                [cell_lon + cell_size, cell_lat + cell_size],
                [cell_lon, cell_lat + cell_size],
                [cell_lon, cell_lat],
            ]
        ]

        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": polygon},
                "properties": {
                    "mean_probability": mean_probability,
                    "dominant_tier": dominant_tier,
                    "point_count": int(len(cell_points)),
                },
            }
        )

    return {"type": "FeatureCollection", "features": features}


def format_intersection_label(row: pd.Series) -> str:
    """Falls back to node id + coordinates if a human-readable
    intersection_label column wasn't included in the demo export."""
    if "intersection_label" in row and pd.notna(row["intersection_label"]):
        return str(row["intersection_label"])
    return f"OSM node {row['node_id']} | {row['latitude']:.4f}, {row['longitude']:.4f}"


@st.cache_data(show_spinner=False)
def cached_risk_grid(rows: pd.DataFrame) -> dict:
    """build_risk_grid, cached. Pass only the columns it needs
    (latitude, longitude, predicted_probability, risk_tier) so hashing is cheap."""
    return build_risk_grid(rows)
