"""Streamlit-free core of SafeCross AI scoring and presentation logic.

Everything here is plain Python (NumPy / pandas) with no Streamlit import, so it can be used by the
Streamlit app (via app_utils.py) AND by the Progressive Web App's API server (pwa/server).
Nothing in this module trains or fits a model, and nothing reads files: loading and caching live in the
callers.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Which areas exist, and whether the model was trained and validated on them. File locations are NOT here:
# each caller knows where its own files live. "nyc" is what the model was trained and validated on; every other
# region is a TRANSFER region (see score_region).
REGION_META = {
    "nyc": {"label": "New York City", "validated": True},
    "westchester": {"label": "Westchester County", "validated": False},
}


# A small, documented fallback list used to rank "top model signals" only if
# the optional permutation_importance.csv isn't present in this deployment.
# Ordered by what Notebook 2 showed mattered most: long-run crash history first,
# then recent history, then road-design context.
FALLBACK_SIGNAL_FEATURES = [
    "crashes_ewm_hl26w",
    "crash_rate_all_history",
    "crashes_last_52w",
    "weeks_since_last_crash",
    "crashes_last_4w",
    "neighbor_crashes_52w_400m",
    "max_connecting_speed_limit",
    "street_count",
    "max_connecting_lanes",
    "touches_oneway_street",
    "is_traffic_signal",
]

# Features that describe WHERE or WHEN a row is rather than the intersection itself.
# Season and the citywide crash totals are identical for every intersection in a given
# week, and coordinates are only a location proxy, so none of them can explain why one
# intersection ranks above another. They are skipped when picking "top signals".
# ("current_week_" is the weather prefix older models used; kept so they still load.)
NON_SIGNAL_FEATURES = {"latitude", "longitude"}

NON_SIGNAL_PREFIXES = ("current_week_", "week_of_year", "citywide_")

def is_intersection_signal(feature: str) -> bool:
    return feature not in NON_SIGNAL_FEATURES and not feature.startswith(NON_SIGNAL_PREFIXES)


class _CrashHistoryFeatures:
    """The features a TRANSFER region (no crash records) has no values for, so they are blanked before scoring.

    Decided by Notebook 2's naming rules rather than a hand-kept list, so a new crash-history feature can't be
    forgotten here: anything derived from an area's own crash records names what it counts (crash, injury,
    killed, casualty), and anything summed over nearby intersections starts with "neighbor_". Coordinates are
    blanked too (transfer areas lie outside the training map). Citywide totals are NOT blanked: like the season,
    build_westchester_assets.py copies them from the NYC snapshot week."""

    MARKERS = ("crash", "injur", "killed", "casualt")

    def __contains__(self, feature: object) -> bool:
        if not isinstance(feature, str) or feature.startswith("citywide_"):
            return False
        return feature in ("latitude", "longitude") or feature.startswith("neighbor_") or any(marker in feature for marker in self.MARKERS)


TRANSFER_BLANKED_FEATURES = _CrashHistoryFeatures()


# Plain-language names for model features, used wherever a feature name is shown to a person.
FEATURE_DISPLAY_NAMES = {
    "crashes_last_1w": "Crashes this week",
    "crashes_last_4w": "Crashes, last 4 weeks",
    "crashes_last_8w": "Crashes, last 8 weeks",
    "crashes_last_13w": "Crashes, last 13 weeks",
    "crashes_last_26w": "Crashes, last 26 weeks",
    "crashes_last_52w": "Crashes, last 52 weeks",
    "crashes_last_104w": "Crashes, last 2 years",
    "crash_weeks_last_52w": "Weeks with a crash, last 52 weeks",
    "crash_weeks_last_156w": "Weeks with a crash, last 3 years",
    "crash_rate_all_history": "Crashes per week since 2012",
    "crashes_ewm_hl4w": "Crashes per week, recent trend",
    "crashes_ewm_hl26w": "Crashes per week, past half-year trend",
    "crashes_ewm_hl52w": "Crashes per week, past year trend",
    "crashes_ewm_hl104w": "Crashes per week, two-year trend",
    "injuries_last_4w": "Injuries, last 4 weeks",
    "injuries_last_52w": "Injuries, last 52 weeks",
    "injuries_ewm_hl52w": "Injuries per week, past year trend",
    "killed_last_156w": "Deaths, last 3 years",
    "pedestrian_casualty_crashes_last_8w": "Pedestrian injury crashes, last 8 weeks",
    "pedestrian_casualty_crashes_last_52w": "Pedestrian injury crashes, last 52 weeks",
    "pedestrian_casualty_ewm_hl52w": "Pedestrian injury crashes per week, past year trend",
    "cyclist_casualty_crashes_last_8w": "Cyclist injury crashes, last 8 weeks",
    "cyclist_casualty_crashes_last_52w": "Cyclist injury crashes, last 52 weeks",
    "cyclist_casualty_ewm_hl52w": "Cyclist injury crashes per week, past year trend",
    "weeks_since_last_crash": "Weeks since the last crash",
    "relative_crash_rate_52w": "Crash rate vs. the average intersection, last 52 weeks",
    "neighbor_crashes_4w_150m": "Crashes within 150 m, last 4 weeks",
    "neighbor_crashes_52w_150m": "Crashes within 150 m, last 52 weeks",
    "neighbor_crashes_4w_400m": "Crashes within 400 m, last 4 weeks",
    "neighbor_crashes_52w_400m": "Crashes within 400 m, last 52 weeks",
    "neighbor_crashes_ewm_hl26w_400m": "Crashes per week within 400 m, past half-year trend",
    "neighbor_crash_rate_all_history_400m": "Crashes per week within 400 m since 2012",
    "intersections_within_150m": "Intersections within 150 m",
    "intersections_within_400m": "Intersections within 400 m",
    "street_count": "Streets meeting here",
    "max_connecting_speed_limit": "Highest speed limit (mph)",
    "max_connecting_lanes": "Most lanes on a connecting street",
    "touches_oneway_street": "Touches a one-way street",
    "is_traffic_signal": "Traffic signal",
    "is_crossing_tagged": "Marked crosswalk",
}


def feature_display_name(name: str) -> str:
    return FEATURE_DISPLAY_NAMES.get(name, name.replace("_", " "))

def unvalidated_note(region_labels: list[str]) -> str:
    names = " and ".join(region_labels)
    return (
        f"**{names}: unvalidated estimate.** The New York City model was applied to the area's road layout, but there is no "
        "crash history there, so the ranking comes from road design alone. Its tiers compare intersections within the area "
        "with each other, not with New York City, and nothing has checked them against real crashes."
    )

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

# --- Prediction and presentation -----------------------------------------
def predict_risk(
    bundle: dict,
    rows: pd.DataFrame,
    blank_features: set[str] | frozenset[str] = frozenset(),
    allow_missing: bool = False,
) -> np.ndarray:
    """Runs the frozen preprocessor + model on raw feature rows and returns
    predicted probabilities. This is the ONLY place inference happens.

    For a validated region every model column must be present (a missing one raises KeyError, so a
    mismatched export fails loudly). For a transfer region, pass `blank_features` (set to NaN before
    scoring, so the model's imputer treats them as typical) and `allow_missing=True` (columns the
    region has no data for, such as crash history, are created as NaN)."""
    raw_features = bundle["raw_features"]
    model_input = rows.reindex(columns=raw_features) if allow_missing else rows[raw_features].copy()
    blank = [feature for feature in raw_features if feature in blank_features]
    if blank:
        model_input[blank] = np.nan
    transformed = bundle["preprocessor"].transform(model_input)
    return bundle["model"].predict_proba(transformed)[:, 1]

def score_region(bundle: dict, frame: pd.DataFrame, region_key: str) -> pd.DataFrame:
    """Score one region's rows. Tiers and percentiles are computed within the region."""
    region = REGION_META[region_key]
    frame = frame.copy()
    if region["validated"]:
        frame["predicted_probability"] = predict_risk(bundle, frame)
    else:
        frame["predicted_probability"] = predict_risk(
            bundle, frame, blank_features=TRANSFER_BLANKED_FEATURES, allow_missing=True
        )
    frame["risk_tier"] = assign_risk_tier(frame["predicted_probability"])
    frame["risk_percentile"] = frame["predicted_probability"].rank(pct=True) * 100
    frame["region"] = region_key
    frame["region_label"] = region["label"]
    frame["validated"] = bool(region["validated"])
    return frame

def same_region_rows(rows: pd.DataFrame, row: pd.Series) -> pd.DataFrame:
    """The rows in `rows` from the same region as `row` (used as the reference when saying how a value
    compares with other intersections)."""
    if "region" in rows.columns and "region" in row.index:
        return rows.loc[rows["region"] == row["region"]]
    return rows

def fallback_label(latitude, longitude) -> str:
    """Used only when street names are unavailable for an intersection (see scripts/build_intersection_info.py)."""
    return f"Intersection near {float(latitude):.4f}, {float(longitude):.4f}"

def merge_intersection_info(frame: pd.DataFrame, info: pd.DataFrame | None) -> pd.DataFrame:
    """Joins the table scripts/build_intersection_info.py writes (street names, sidewalk, bike lane, lighting,
    bridge/tunnel, roundabout, traffic control) onto the scored intersections by node_id. Safe to call with
    None or an empty table: the frame is returned unchanged and labels fall back to coordinates."""
    frame = frame.copy()
    if info is None or info.empty or "node_id" not in info.columns:
        return frame
    info = info.copy()
    info["node_id"] = info["node_id"].astype(str)
    info = info.drop_duplicates("node_id").set_index("node_id")
    key = frame["node_id"].astype(str)
    if "label" in info.columns:
        label = key.map(info["label"]).replace("", np.nan)
        if "intersection_label" in frame.columns:
            label = label.where(label.notna(), frame["intersection_label"])
        frame["intersection_label"] = label
    for column in ("streets", "sidewalk", "bike_lane", "lit", "node_control"):
        if column in info.columns:
            frame[column] = key.map(info[column])
    for column in ("bridge_or_tunnel", "roundabout"):
        if column in info.columns:
            frame[column] = pd.to_numeric(key.map(info[column]), errors="coerce")
    return frame

def add_intersection_labels(frame: pd.DataFrame) -> pd.DataFrame:
    """Guarantees a human-readable intersection_label on every row (vectorized, so it is cheap to repeat).
    Uses the street-name label where merge_intersection_info supplied one, otherwise falls back to coordinates.
    It never shows a raw OSM node number."""
    frame = frame.copy()
    fallback = "Intersection near " + frame["latitude"].map("{:.4f}".format) + ", " + frame["longitude"].map("{:.4f}".format)
    if "intersection_label" in frame.columns:
        label = frame["intersection_label"].astype("object")
        label = label.where(label.notna() & (label.astype(str).str.strip() != ""), fallback)
        # Labels saved by an older export read "OSM node 123 | lat, lng"; never show those.
        stale = label.astype(str).str.startswith("OSM node")
        frame["intersection_label"] = label.where(~stale, fallback).astype(str)
    else:
        frame["intersection_label"] = fallback
    return frame

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

    controlled = str(row.get("node_control", "")) in ("traffic_signals", "stop", "give_way", "mini_roundabout")
    if row.get("is_traffic_signal", 0) == 0 and not controlled and row.get("street_count", 0) and row["street_count"] >= 4:
        measures.append("Review whether signal or stop control is warranted")

    if not measures:
        measures.append("No rule-based candidate measure triggered — recommend manual site review")

    return measures

def build_risk_grid(rows: pd.DataFrame, target_bins: int = 30, cell_size: float | None = None) -> dict:
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

    if cell_size is None:
        lat_span = max(rows["latitude"].max() - rows["latitude"].min(), 1e-6)
        lon_span = max(rows["longitude"].max() - rows["longitude"].min(), 1e-6)
        cell_size = max(lat_span, lon_span) / target_bins
        lon_size = cell_size
    else:
        # `cell_size` is the cell height in degrees of latitude. A degree of longitude is shorter by cos(latitude), so
        # the cell is widened by the same factor to stay roughly square on the ground.
        lon_size = cell_size / max(np.cos(np.radians(float(rows["latitude"].median()))), 0.2)

    grid_rows = rows.copy()
    grid_rows["cell_lat"] = (grid_rows["latitude"] // cell_size) * cell_size
    grid_rows["cell_lon"] = (grid_rows["longitude"] // lon_size) * lon_size

    cell_groups = grid_rows.groupby(["cell_lat", "cell_lon"])

    features = []
    for (cell_lat, cell_lon), cell_points in cell_groups:
        mean_probability = float(cell_points["predicted_probability"].mean())
        dominant_tier = cell_points["risk_tier"].mode().iat[0] if "risk_tier" in cell_points else None

        polygon = [
            [
                [cell_lon, cell_lat],
                [cell_lon + lon_size, cell_lat],
                [cell_lon + lon_size, cell_lat + cell_size],
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
    """The street-name label if there is one, otherwise the coordinates (never a raw OSM node number)."""
    label = row.get("intersection_label") if hasattr(row, "get") else None
    if label is not None and pd.notna(label) and str(label).strip() and not str(label).startswith("OSM node"):
        return str(label)
    return fallback_label(row["latitude"], row["longitude"])

# --- What to show about an intersection (the details panel) --------------------------------------
ROAD_CLASS_NAMES = {
    "motorway": "Motorway / expressway", "trunk": "Major arterial", "primary": "Primary road", "secondary": "Secondary road",
    "tertiary": "Tertiary road", "residential": "Residential street", "unclassified": "Minor road",
    "living_street": "Living street", "service": "Service road",
}
CONTROL_NAMES = {
    "traffic_signals": "Traffic signal", "stop": "Stop sign", "give_way": "Yield sign",
    "mini_roundabout": "Mini roundabout", "crossing": "Marked crossing",
}
FAST_MPH = 35  # same cut-off candidate_measures_for_row uses

def _number(row, name):
    value = row.get(name) if hasattr(row, "get") else None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(number) else number

def intersection_facts(row: pd.Series, validated: bool = True) -> list[dict]:
    """Plain-language facts about one intersection, grouped for display: [{"title", "items": [{"label", "value",
    "tone"}]}]. tone is "good", "warn" or "neutral" (used only for a small colour cue). Anything the data does not
    say is reported as such: a missing OpenStreetMap tag is "not mapped", never "no"."""
    items_road, items_walk, items_history = [], [], []

    speed = _number(row, "max_connecting_speed_limit")
    if speed is None:
        items_road.append({"label": "Speed limit", "value": "Not recorded in OpenStreetMap", "tone": "neutral"})
    else:
        items_road.append({"label": "Speed limit (fastest connecting street)", "value": f"{speed:.0f} mph", "tone": "warn" if speed >= FAST_MPH else "neutral"})
    lanes = _number(row, "max_connecting_lanes")
    items_road.append({"label": "Lanes (widest connecting street)", "value": "Not recorded" if lanes is None else f"{lanes:.0f}", "tone": "warn" if (lanes or 0) >= 4 else "neutral"})
    road_class = row.get("road_class") if hasattr(row, "get") else None
    if road_class is not None and pd.notna(road_class):
        first = str(road_class).replace("[", "").replace("]", "").replace("'", "").split(",")[0].split("|")[0].strip()
        items_road.append({"label": "Biggest street type", "value": ROAD_CLASS_NAMES.get(first, first.replace("_", " ").capitalize()), "tone": "neutral"})
    streets = _number(row, "street_count")
    names = row.get("streets") if hasattr(row, "get") else None
    if streets is not None:
        items_road.append({"label": "Streets meeting here", "value": f"{streets:.0f}", "tone": "neutral"})
    if names is not None and pd.notna(names) and str(names).strip():
        items_road.append({"label": "Street names", "value": str(names).replace(" | ", ", "), "tone": "neutral"})
    oneway = _number(row, "touches_oneway_street")
    if oneway is not None:
        items_road.append({"label": "One-way street", "value": "A one-way street meets here" if oneway else "No one-way street", "tone": "neutral"})
    control = row.get("node_control") if hasattr(row, "get") else None
    signal = _number(row, "is_traffic_signal")
    if signal:
        control_text, control_tone = "Traffic signal", "good"
    elif control is not None and pd.notna(control) and str(control) in CONTROL_NAMES:
        control_text, control_tone = CONTROL_NAMES[str(control)], "neutral"
    else:
        control_text, control_tone = "None mapped", "warn" if (streets or 0) >= 4 else "neutral"
    items_road.append({"label": "Traffic control", "value": control_text, "tone": control_tone})
    if _number(row, "roundabout"):
        items_road.append({"label": "Roundabout", "value": "Yes", "tone": "neutral"})
    if _number(row, "bridge_or_tunnel"):
        items_road.append({"label": "Structure", "value": "On a bridge or tunnel", "tone": "neutral"})

    crossing = _number(row, "is_crossing_tagged")
    if crossing is not None:
        items_walk.append({"label": "Marked crosswalk", "value": "Mapped here" if crossing else "Not mapped here", "tone": "good" if crossing else "neutral"})
    sidewalk = row.get("sidewalk") if hasattr(row, "get") else None
    sidewalk_text = {
        "yes": ("Sidewalk mapped on a connecting street", "good"),
        "partial": ("Sidewalk on one side only", "warn"),
        "no": ("Tagged as having no sidewalk", "warn"),
    }.get(str(sidewalk), ("Not mapped in OpenStreetMap (can't tell)", "neutral"))
    items_walk.append({"label": "Sidewalk", "value": sidewalk_text[0], "tone": sidewalk_text[1]})
    bike = row.get("bike_lane") if hasattr(row, "get") else None
    bike_text = {"yes": ("Bike lane mapped on a connecting street", "good"), "no": ("Tagged as having none", "neutral")}.get(str(bike), ("Not mapped in OpenStreetMap (can't tell)", "neutral"))
    items_walk.append({"label": "Bike lane", "value": bike_text[0], "tone": bike_text[1]})
    lit = row.get("lit") if hasattr(row, "get") else None
    lit_text = {"yes": ("Street lighting mapped", "good"), "no": ("Tagged as unlit", "warn")}.get(str(lit), ("Not mapped in OpenStreetMap (can't tell)", "neutral"))
    items_walk.append({"label": "Street lighting", "value": lit_text[0], "tone": lit_text[1]})

    if validated:
        c4, c8 = _number(row, "crashes_last_4w"), _number(row, "crashes_last_8w")
        items_history.append({"label": "Crashes, last 4 weeks", "value": "not available" if c4 is None else str(int(c4)), "tone": "warn" if (c4 or 0) > 0 else "neutral"})
        items_history.append({"label": "Crashes, last 8 weeks", "value": "not available" if c8 is None else str(int(c8)), "tone": "warn" if (c8 or 0) > 0 else "neutral"})
        c52 = _number(row, "crashes_last_52w")  # only present for models trained with long-run history
        if c52 is not None:
            items_history.append({"label": "Crashes, last 52 weeks", "value": str(int(c52)), "tone": "warn" if c52 > 0 else "neutral"})
        injuries = _number(row, "injuries_last_4w")
        items_history.append({"label": "Injuries, last 4 weeks", "value": "not available" if injuries is None else str(int(injuries)), "tone": "warn" if (injuries or 0) > 0 else "neutral"})
        ped = _number(row, "pedestrian_casualty_crashes_last_8w")
        cyc = _number(row, "cyclist_casualty_crashes_last_8w")
        items_history.append({"label": "Pedestrian injury crashes, last 8 weeks", "value": "not available" if ped is None else str(int(ped)), "tone": "warn" if (ped or 0) > 0 else "neutral"})
        items_history.append({"label": "Cyclist injury crashes, last 8 weeks", "value": "not available" if cyc is None else str(int(cyc)), "tone": "warn" if (cyc or 0) > 0 else "neutral"})
        since = _number(row, "weeks_since_last_crash")
        if since is not None:
            items_history.append({"label": "Weeks since the last crash", "value": f"{since:.0f}", "tone": "neutral"})
    else:
        items_history.append({"label": "Crash history", "value": "Not available for this area", "tone": "neutral"})

    return [
        {"title": "Road layout and traffic control", "items": items_road},
        {"title": "Walking and cycling", "items": items_walk},
        {"title": "Recent crash history", "items": items_history},
    ]
