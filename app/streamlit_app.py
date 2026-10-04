"""SafeCross AI — Streamlit demo app.

Run from the REPOSITORY ROOT (not from inside app/):

    streamlit run app/streamlit_app.py

This app only loads files Notebook 2, Notebook 3, and
scripts/export_streamlit_assets.py already saved to disk. It never trains or
retrains a model.
"""

from __future__ import annotations

import sys
from pathlib import Path

import branca.colormap
import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

# Allow "from app_utils import ..." whether Streamlit is launched from the
# repo root (the documented, correct way) or accidentally from inside app/.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app_utils import (  # noqa: E402
    assign_risk_tier,
    build_risk_grid,
    candidate_measures_for_row,
    format_intersection_label,
    load_demo_data,
    load_metadata,
    load_model_bundle,
    load_signal_features,
    load_test_metrics,
    predict_risk,
    top_signals_for_row,
)

st.set_page_config(page_title="SafeCross AI", layout="wide")

# --- Load everything up front (all cached; fast after first load) --------
bundle = load_model_bundle()
metadata = load_metadata()
demo_data = load_demo_data()
test_metrics = load_test_metrics()
signal_features = load_signal_features(bundle["numeric_features"])

# --- Run inference once, on the whole demo set ----------------------------
demo_data = demo_data.copy()
demo_data["predicted_probability"] = predict_risk(bundle, demo_data)
demo_data["risk_tier"] = assign_risk_tier(demo_data["predicted_probability"])
demo_data["risk_percentile"] = demo_data["predicted_probability"].rank(pct=True) * 100

# The full dataset is kept — nothing is discarded. What made the app slow was
# rendering everything at once, not having it loaded. The table below and the
# map's node markers each load incrementally instead (see PAGE_SIZE and the
# viewport-based marker loading further down).

st.title("SafeCross AI — Intersection Risk Review")
st.caption(
    "Public data → intersection-week features → explainable ML model → "
    "relative risk + safety-review signals."
)

explore_tab, model_tab, limitations_tab = st.tabs(["Explore", "Model", "Limitations"])

# =========================== EXPLORE TAB ==================================
with explore_tab:
    week_options = sorted(demo_data["week_start"].unique().tolist()) if "week_start" in demo_data.columns else []
    if week_options:
        selected_week = st.selectbox("Historical snapshot week", week_options, index=len(week_options) - 1)
        week_rows = demo_data.loc[demo_data["week_start"] == selected_week].copy()
    else:
        week_rows = demo_data.copy()

    st.caption(f"{len(week_rows):,} intersections in this snapshot.")

    week_rows["intersection_label"] = week_rows.apply(format_intersection_label, axis=1)

    tier_options = ["Highest-priority (top 10%)", "Elevated relative risk", "Moderate relative risk", "Lower relative risk"]
    selected_tiers = st.multiselect("Filter by relative risk tier", tier_options, default=tier_options)
    filtered_rows = week_rows.loc[week_rows["risk_tier"].isin(selected_tiers)].sort_values(
        "predicted_probability", ascending=False
    )

    left_column, right_column = st.columns([1, 1])

    with left_column:
        st.subheader("Flagged intersections")

        # Load the table incrementally instead of rendering every row at
        # once — the full dataset stays available, just not all rendered up
        # front. Resets back to one page whenever the active filters change,
        # so "load more" always means "more of THIS filter", not stale rows
        # from a previous selection.
        PAGE_SIZE = 50
        filter_signature = (selected_week, tuple(sorted(selected_tiers)))
        if st.session_state.get("table_filter_signature") != filter_signature:
            st.session_state.table_filter_signature = filter_signature
            st.session_state.table_rows_shown = PAGE_SIZE

        rows_shown = min(st.session_state.table_rows_shown, len(filtered_rows))
        visible_rows = filtered_rows.head(rows_shown)

        st.dataframe(
            visible_rows[["intersection_label", "risk_tier", "risk_percentile"]].rename(
                columns={
                    "intersection_label": "Intersection",
                    "risk_tier": "Relative risk",
                    "risk_percentile": "Percentile",
                }
            ),
            use_container_width=True,
            hide_index=True,
            height=420,
        )

        st.caption(f"Showing {rows_shown:,} of {len(filtered_rows):,} intersections, ranked by risk.")

        if rows_shown < len(filtered_rows):
            if st.button(f"Load {min(PAGE_SIZE, len(filtered_rows) - rows_shown)} more"):
                st.session_state.table_rows_shown += PAGE_SIZE
                st.rerun()

        selected_label = st.selectbox(
            "Select an intersection to explain",
            visible_rows["intersection_label"].tolist() if len(visible_rows) else [],
        )

    with right_column:
        st.subheader("Map")
        st.caption("Zoomed out: area-level risk. Zoom in to see individual intersections.")

        if len(filtered_rows) > 0 and {"latitude", "longitude"}.issubset(filtered_rows.columns):
            # ZOOM_SWITCH_LEVEL is the Leaflet zoom level at which the map
            # flips from the grid choropleth to individual node markers.
            # Start zoomed OUT (below the switch level), so the choropleth is
            # what the user sees first.
            ZOOM_SWITCH_LEVEL = 14

            # Persist the map's last known center/zoom/viewport across
            # Streamlit reruns (st_folium triggers a rerun on every pan/zoom).
            # This is what fixes the "snaps back on pan" bug: without this,
            # the map was being rebuilt from the DATA's median location on
            # every single rerun, throwing away wherever the user had just
            # panned to. It also lets node markers be built ONLY for whatever
            # is currently in view, instead of embedding every marker into
            # the page up front.
            if "map_center" not in st.session_state:
                st.session_state.map_center = [filtered_rows["latitude"].median(), filtered_rows["longitude"].median()]
            if "map_zoom" not in st.session_state:
                st.session_state.map_zoom = ZOOM_SWITCH_LEVEL - 3
            if "map_bounds" not in st.session_state:
                st.session_state.map_bounds = None

            risk_map = folium.Map(
                location=st.session_state.map_center,
                zoom_start=st.session_state.map_zoom,
                tiles="cartodbpositron",
            )

            tier_colors = {
                "Highest-priority (top 10%)": "red",
                "Elevated relative risk": "orange",
                "Moderate relative risk": "blue",
                "Lower relative risk": "gray",
            }

            # --- Layer 1: grid choropleth (shown when zoomed out) ---------
            grid_layer = folium.FeatureGroup(name="Area risk", show=True)

            risk_grid = build_risk_grid(filtered_rows)
            probabilities = [feature["properties"]["mean_probability"] for feature in risk_grid["features"]]

            if probabilities:
                color_scale = branca.colormap.LinearColormap(
                    colors=["#f0f0f0", "#fdae61", "#d7191c"],
                    vmin=min(probabilities),
                    vmax=max(probabilities),
                ).to_step(6)

                def style_grid_cell(feature: dict) -> dict:
                    return {
                        "fillColor": color_scale(feature["properties"]["mean_probability"]),
                        "color": "#888888",
                        "weight": 0.5,
                        "fillOpacity": 0.65,
                    }

                folium.GeoJson(
                    risk_grid,
                    style_function=style_grid_cell,
                    tooltip=folium.GeoJsonTooltip(
                        fields=["dominant_tier", "point_count"],
                        aliases=["Dominant risk tier", "Intersections in area"],
                    ),
                ).add_to(grid_layer)

                color_scale.caption = "Mean predicted risk (area average)"
                color_scale.add_to(risk_map)

            grid_layer.add_to(risk_map)

            # --- Layer 2: individual node markers (shown when zoomed in) --
            # Only build markers for rows inside the last known viewport, and
            # only once the map is actually zoomed in past the switch level.
            # On first load there is no viewport yet, so this layer starts
            # empty — nodes populate in only as the user zooms/pans, rather
            # than every marker being embedded in the page from the start.
            node_layer = folium.FeatureGroup(name="Intersections", show=False)

            bounds = st.session_state.map_bounds
            zoomed_in_enough = st.session_state.map_zoom >= ZOOM_SWITCH_LEVEL

            if zoomed_in_enough and bounds:
                south = bounds["_southWest"]["lat"]
                north = bounds["_northEast"]["lat"]
                west = bounds["_southWest"]["lng"]
                east = bounds["_northEast"]["lng"]

                in_view_rows = filtered_rows.loc[
                    filtered_rows["latitude"].between(south, north) & filtered_rows["longitude"].between(west, east)
                ]
            else:
                in_view_rows = filtered_rows.iloc[0:0]

            for _, row in in_view_rows.iterrows():
                folium.CircleMarker(
                    location=[row["latitude"], row["longitude"]],
                    radius=5 if row["intersection_label"] == selected_label else 3,
                    color=tier_colors.get(row["risk_tier"], "gray"),
                    fill=True,
                    fill_opacity=0.8,
                    tooltip=f"{row['intersection_label']} — {row['risk_tier']}",
                ).add_to(node_layer)

            node_layer.add_to(risk_map)
            st.caption(f"{len(in_view_rows):,} intersections rendered in the current view.")

            # --- Wire up automatic zoom-based switching --------------------
            # Folium/Leaflet has no built-in "swap layer at this zoom level"
            # behavior, so this adds a small script that listens for zoom
            # changes and toggles which FeatureGroup is attached to the map.
            map_variable = risk_map.get_name()
            grid_variable = grid_layer.get_name()
            node_variable = node_layer.get_name()

            zoom_switch_script = f"""
            <script>
            function safecrossApplyZoomLayer() {{
                if ({map_variable}.getZoom() < {ZOOM_SWITCH_LEVEL}) {{
                    if ({map_variable}.hasLayer({node_variable})) {{ {map_variable}.removeLayer({node_variable}); }}
                    if (!{map_variable}.hasLayer({grid_variable})) {{ {map_variable}.addLayer({grid_variable}); }}
                }} else {{
                    if ({map_variable}.hasLayer({grid_variable})) {{ {map_variable}.removeLayer({grid_variable}); }}
                    if (!{map_variable}.hasLayer({node_variable})) {{ {map_variable}.addLayer({node_variable}); }}
                }}
            }}
            {map_variable}.on("zoomend", safecrossApplyZoomLayer);
            safecrossApplyZoomLayer();
            </script>
            """
            risk_map.get_root().html.add_child(folium.Element(zoom_switch_script))

            map_state = st_folium(
                risk_map,
                width=None,
                height=420,
                returned_objects=["bounds", "zoom", "center"],
            )

            # Persist whatever the map reports back, so the NEXT rerun (the
            # next time the user interacts with the map) knows where the
            # user actually is — both to stop it snapping back to the data's
            # median location, and so node markers can be built only for
            # what's in view.
            if map_state:
                if map_state.get("bounds"):
                    st.session_state.map_bounds = map_state["bounds"]
                if map_state.get("zoom") is not None:
                    st.session_state.map_zoom = map_state["zoom"]
                if map_state.get("center"):
                    st.session_state.map_center = [map_state["center"]["lat"], map_state["center"]["lng"]]
        else:
            st.info("No location data available to plot for this filter.")

    if selected_label and len(filtered_rows) > 0:
        st.divider()
        st.subheader(f"Explanation: {selected_label}")

        selected_row = filtered_rows.loc[filtered_rows["intersection_label"] == selected_label].iloc[0]

        explanation_columns = st.columns(3)
        explanation_columns[0].metric("Relative risk", selected_row["risk_tier"])
        explanation_columns[1].metric("Percentile", f"{selected_row['risk_percentile']:.1f}")
        if "crashes_last_4w" in selected_row:
            explanation_columns[2].metric("Crashes, last 4 weeks", int(selected_row["crashes_last_4w"]))

        signals = top_signals_for_row(selected_row, signal_features)
        if signals:
            st.markdown("**Top model signals for this intersection:**")
            for feature, value in signals:
                st.write(f"- {feature.replace('_', ' ')}: {value}")

        st.markdown("**Candidate safety-review areas** *(rule-based suggestions, not a model output):*")
        for measure in candidate_measures_for_row(selected_row):
            st.write(f"- {measure}")

        st.caption(
            "These are starting points for further review, not engineering "
            "recommendations. The model cannot prove any location is "
            "dangerous — only that it resembles ones that had a crash the "
            "following period."
        )

# ============================ MODEL TAB ===================================
with model_tab:
    st.subheader("Selected model")

    info_columns = st.columns(3)
    info_columns[0].metric("Model", metadata.get("selected_model", "unknown"))
    info_columns[1].metric("Decision threshold", round(float(metadata.get("selected_threshold", 0)), 3))
    info_columns[2].metric("Prediction horizon", f"{metadata.get('prediction_horizon_weeks', '?')} week(s)")

    st.write(f"**Prediction target:** `{metadata.get('target', 'unknown')}`")
    st.write(f"**XGBoost training device:** {metadata.get('xgboost_training_device', 'n/a')} (inference always runs on CPU in this app)")

    st.info(
        "Predicted probabilities are not shown as literal chances of a crash "
        "(e.g. \"68%\"). Calibration on the held-out test period is weak "
        "enough that a specific percentage would overstate precision — so "
        "the app instead ranks locations against each other and reports a "
        "relative risk tier."
    )

    if test_metrics:
        st.subheader("Held-out test performance")
        metrics_to_show = {
            key: value
            for key, value in test_metrics.items()
            if isinstance(value, (int, float))
        }
        st.dataframe(pd.Series(metrics_to_show, name="value").to_frame(), use_container_width=True)
    else:
        st.caption("No saved test metrics found — this section is optional and skipped.")

# ========================= LIMITATIONS TAB ================================
with limitations_tab:
    st.subheader("Limitations")
    st.markdown(
        """
- **Not exposure-normalized.** Predictions do not account for pedestrian or
  vehicle volume, since that data is not yet directly included. A busy but
  well-managed intersection can rank similarly to a quiet, poorly-designed one.
- **Reporting and location error.** Crash records depend on what was reported
  and how precisely it was geocoded; both introduce noise into the crash
  history features.
- **Incomplete OSM tagging.** Some road-design attributes (e.g. crosswalk
  tags) are inconsistently present in the source map data and were excluded
  from the model rather than guessed at — see Notebook 2's feature audit.
- **One year of data.** Validation and test periods are relatively short
  (a few months each), so results may be sensitive to that specific window.
- **Feature importance is not causation.** It shows what the model relies
  on, not what causes crashes. Many flagged locations simply have more
  recent crash activity — that's a reason for follow-up, not proof of danger.
- **Candidate safety measures are not recommendations.** They are simple,
  transparent rules meant to give a reviewer a starting point. Every flagged
  location needs site review and external road-safety evidence before any
  action is taken.
        """
    )