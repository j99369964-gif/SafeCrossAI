"""SafeCross AI — Streamlit demo app.

Run from the REPOSITORY ROOT (not from inside app/):

    streamlit run app/streamlit_app.py

This app only loads files Notebook 2, Notebook 3, and
scripts/export_streamlit_assets.py already saved to disk. It never trains or
retrains a model.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import branca.colormap
import folium
import pandas as pd
import streamlit as st
from branca.element import MacroElement, Template
from streamlit_folium import st_folium

# Allow "from app_utils import ..." whether Streamlit is launched from the
# repo root (the documented, correct way) or accidentally from inside app/.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app_utils import (  # noqa: E402
    cached_risk_grid,
    candidate_measures_for_row,
    load_metadata,
    load_model_bundle,
    load_scored_demo_data,
    load_signal_features,
    load_test_metrics,
    top_signals_for_row,
)

st.set_page_config(page_title="SafeCross AI", layout="wide")

# --- Load everything up front (all cached; fast after first load) --------
bundle = load_model_bundle()
metadata = load_metadata()
test_metrics = load_test_metrics()
signal_features = load_signal_features(bundle["numeric_features"])

# --- Scored demo data (inference runs ONCE and is cached) -----------------
# Streamlit re-runs this whole script whenever a widget changes. Scoring every
# intersection and building labels therefore lives in a cached function
# (app_utils.load_scored_demo_data) rather than here: with ~40,000 citywide
# intersections, doing it here would repeat it on every filter change.
demo_data = load_scored_demo_data()

# The full dataset is kept — nothing is discarded. What made the app slow was
# rendering everything at once, not having it loaded. The table below and the
# map's node markers each load incrementally instead (see PAGE_SIZE and the
# viewport-based marker loading further down).

st.title("SafeCross AI — Explainable road-safety screening for urban intersections")
st.write(
    "SafeCross uses public crash, roadway, time, and weather data to identify "
    "intersections that may deserve closer safety review and explain the "
    "signals behind each ranking."
)

explore_tab, model_tab, limitations_tab = st.tabs(["Explore", "Model", "Limitations"])

# =========================== EXPLORE TAB ==================================
with explore_tab:
    st.header("How to explore")
    st.write("1. Filter by risk level and snapshot week in the sidebar")
    st.write("2. Zoom into an area to reveal individual intersections")
    st.write("3. Hover over an intersection for details")
    st.write("4. Select an intersection in the sidebar (or look one up by OSM node id) for a deeper explanation")

    # --- Sidebar: all filters + the intersection selector live here, so
    # they stay visible and out of the way of the map/table below. ---------
    with st.sidebar:
        st.subheader("Filters")

        week_options = sorted(demo_data["week_start"].unique().tolist()) if "week_start" in demo_data.columns else []
        if week_options:
            selected_week = st.selectbox("Historical snapshot week", week_options, index=len(week_options) - 1)
            week_rows = demo_data.loc[demo_data["week_start"] == selected_week].copy()
        else:
            selected_week = None
            week_rows = demo_data.copy()

        tier_options = [
            "Highest-priority (top 10%)",
            "Elevated relative risk",
            "Moderate relative risk",
            "Lower relative risk",
        ]
        selected_tiers = st.multiselect("Filter by relative risk tier", tier_options, default=tier_options)

        filtered_rows = week_rows.loc[week_rows["risk_tier"].isin(selected_tiers)].sort_values(
            "predicted_probability", ascending=False
        )

        # One selector drives BOTH the map highlight and the explanation
        # panel below — previously these were two separate dropdowns doing
        # the same job.
        #
        # A dropdown listing every intersection in the city (~40,000) is slow to
        # send to the browser and unusable to scroll, so it offers the highest-risk
        # intersections only. Any other intersection can be found by OSM node id.
        SELECTOR_MAX_OPTIONS = 500
        selector_rows = filtered_rows.head(SELECTOR_MAX_OPTIONS)
        selected_label = st.selectbox(
            f"Select an intersection to highlight / explain (optional; top {len(selector_rows):,} by risk)",
            options=[None] + selector_rows["intersection_label"].tolist(),
            index=0,
        )

        lookup_node_id = st.text_input("...or look one up by OSM node id", value="").strip()
        if lookup_node_id:
            lookup_matches = filtered_rows.loc[filtered_rows["node_id"].astype(str) == lookup_node_id]
            if len(lookup_matches) > 0:
                selected_label = lookup_matches["intersection_label"].iloc[0]
            else:
                st.warning("No intersection with that OSM node id in the current filters.")

    # --- Top metrics row -----------------------------------------------
    intersections_metric, high_risk_metric, snapshot_metric = st.columns(3)
    intersections_metric.metric("Intersections in filter", f"{len(filtered_rows):,}")
    high_risk_metric.metric(
        "High-risk intersections",
        f"{len(filtered_rows.loc[filtered_rows['risk_tier'] == 'Highest-priority (top 10%)']):,}",
    )
    # Derived from the actual selected snapshot week rather than a fixed
    # year, so this doesn't go stale the next time the demo data changes.
    snapshot_metric.metric("Snapshot week", str(selected_week) if selected_week is not None else "-")

    st.subheader("Map")
    st.caption(
        "Zoomed out: area-level risk. Zoom in and pan to load individual intersections "
        "(dense areas show up to 1,500 of the highest-risk intersections in view)."
    )

    if len(filtered_rows) > 0 and {"latitude", "longitude"}.issubset(filtered_rows.columns):
        map_center = [filtered_rows["latitude"].median(), filtered_rows["longitude"].median()]

        # ZOOM_SWITCH_LEVEL is the Leaflet zoom level at which the map
        # flips from the grid choropleth to individual node markers.
        ZOOM_SWITCH_LEVEL = 14

        # The map is built fresh from the DATA every rerun, and that's fine:
        # Python only reruns when a real widget changes (filters, the
        # sidebar selector, the table's "load more" button, etc.) - never
        # just from panning or zooming the map. No bounds/zoom/center are
        # read back from st_folium, so moving the map never triggers
        # Streamlit, and there's nothing in session_state to go stale and
        # snap the map back to.
        #
        # prefer_canvas=True: renders markers via a single canvas instead
        # of one SVG element per marker. Markers get added/removed
        # frequently as the user pans, and canvas rendering handles that
        # churn far more cheaply, which noticeably reduces stutter.
        # Starting zoom from the data's extent so the whole study area is visible:
        # about the whole city -> 10, a borough -> 11, smaller -> 12. All of these
        # are below ZOOM_SWITCH_LEVEL, so the area view is what shows first.
        lat_span = filtered_rows["latitude"].max() - filtered_rows["latitude"].min()
        lon_span = (filtered_rows["longitude"].max() - filtered_rows["longitude"].min()) * 0.76  # cos(40.7 deg)
        extent = max(lat_span, lon_span)
        initial_zoom = 10 if extent > 0.3 else 11 if extent > 0.12 else 12

        risk_map = folium.Map(
            location=map_center,
            zoom_start=initial_zoom,
            tiles="https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png?key=cb1_3sq1_1_e7e28384896137cc65ab3b76",
            attr='&copy; <a href="https://carto.com/attributions">CARTO</a>',
            prefer_canvas=True,
        )

        tier_colors = {
            "Highest-priority (top 10%)": "red",
            "Elevated relative risk": "orange",
            "Moderate relative risk": "blue",
            "Lower relative risk": "gray",
        }

        # --- Layer 1: grid choropleth (shown when zoomed out) ---------
        grid_layer = folium.FeatureGroup(name="Area risk", show=True)

        risk_grid = cached_risk_grid(filtered_rows[["latitude", "longitude", "predicted_probability", "risk_tier"]])
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

        # --- Layer 2: individual node markers, loaded/unloaded entirely
        # in the browser, never through Python -------------------------
        # One compact payload is sent to the page ONCE per real rerun, as parallel
        # arrays (not one object with HTML per intersection), so it stays a few MB
        # even for ~40,000 intersections. The rows are already sorted by risk. The
        # browser, on every pan/zoom, finds the points inside the current viewport,
        # draws markers for at most MAX_MARKERS_IN_VIEW of them (highest risk first,
        # plus the selected one), and builds each tooltip only when its marker is
        # created. No server round trip for any of it.
        MAX_MARKERS_IN_VIEW = 1500
        tier_order = list(tier_colors)
        tier_code = filtered_rows["risk_tier"].map({tier: i for i, tier in enumerate(tier_order)})
        tier_code = tier_code.fillna(len(tier_order) - 1).astype(int)

        def integer_column(name: str) -> list[int]:
            if name not in filtered_rows.columns:
                return [0] * len(filtered_rows)
            return filtered_rows[name].fillna(0).astype(int).tolist()

        selected_matches = (filtered_rows["intersection_label"] == selected_label).to_numpy()
        selected_index = int(selected_matches.argmax()) if selected_label and selected_matches.any() else -1

        map_data = {
            "lat": filtered_rows["latitude"].round(5).tolist(),
            "lng": filtered_rows["longitude"].round(5).tolist(),
            "tier": tier_code.tolist(),
            "pct": filtered_rows["risk_percentile"].round(0).astype(int).tolist(),
            "crashes4w": integer_column("crashes_last_4w"),
            "streets": integer_column("street_count"),
            "label": filtered_rows["intersection_label"].tolist(),
            "selected": selected_index,
        }

        map_variable = risk_map.get_name()
        grid_variable = grid_layer.get_name()

        client_side_script_template = """
        (function() {
            var map = __MAP__;
            var gridLayer = __GRID__;
            var D = __DATA__;
            var ZOOM_SWITCH = __ZOOM__;
            var MAX_MARKERS = __MAX_MARKERS__;
            var TIER_COLORS = __TIER_COLORS__;
            var TIER_NAMES = __TIER_NAMES__;

            var markerLayer = L.layerGroup();
            var active = {};

            // Small on-map notice, shown only when a dense view is capped.
            var notice = L.control({position: "bottomleft"});
            notice.onAdd = function() {
                var div = L.DomUtil.create("div", "safecross-notice");
                div.style.cssText = "background:rgba(255,255,255,0.92);padding:4px 8px;border-radius:4px;" +
                                    "font:12px sans-serif;display:none;";
                this._div = div;
                return div;
            };
            notice.addTo(map);
            function setNotice(text) {
                notice._div.style.display = text ? "block" : "none";
                notice._div.textContent = text || "";
            }

            function esc(value) {
                return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
            }
            function tooltipFor(i) {
                return "<b>" + esc(D.label[i]) + "</b><br>" +
                       esc(TIER_NAMES[D.tier[i]]) + "<br>" +
                       "Relative risk percentile: " + D.pct[i] + "th<br>" +
                       "Crashes in previous 4 weeks: " + D.crashes4w[i] + "<br>" +
                       "Connected streets: " + D.streets[i];
            }

            function updateView() {
                if (map.getZoom() < ZOOM_SWITCH) {
                    markerLayer.clearLayers();
                    active = {};
                    if (map.hasLayer(markerLayer)) { map.removeLayer(markerLayer); }
                    if (!map.hasLayer(gridLayer)) { map.addLayer(gridLayer); }
                    setNotice("");
                    return;
                }

                if (map.hasLayer(gridLayer)) { map.removeLayer(gridLayer); }
                if (!map.hasLayer(markerLayer)) { markerLayer.addTo(map); }

                var b = map.getBounds();
                var south = b.getSouth(), north = b.getNorth(), west = b.getWest(), east = b.getEast();
                var visible = {};
                var shown = 0, inView = 0;

                // Points arrive sorted by risk (highest first), so stopping at the cap
                // keeps the highest-risk ones. The selected point is always drawn.
                for (var i = 0; i < D.lat.length; i++) {
                    var lat = D.lat[i], lng = D.lng[i];
                    if (lat < south || lat > north || lng < west || lng > east) { continue; }
                    inView++;
                    var forced = (i === D.selected);
                    if (shown >= MAX_MARKERS && !forced) { continue; }
                    shown++;
                    visible[i] = true;
                    if (!active[i]) {
                        var selected = (i === D.selected);
                        var color = TIER_COLORS[D.tier[i]];
                        var marker = L.circleMarker([lat, lng], {
                            radius: selected ? 7 : 6,
                            color: color,
                            fillColor: color,
                            fill: true,
                            fillOpacity: 0.9,
                            weight: selected ? 3 : 1
                        }).bindTooltip(tooltipFor(i));
                        marker.addTo(markerLayer);
                        active[i] = marker;
                    }
                }

                for (var key in active) {
                    if (!visible[key]) {
                        markerLayer.removeLayer(active[key]);
                        delete active[key];
                    }
                }

                setNotice(inView > shown
                    ? inView.toLocaleString() + " intersections in view; showing the " +
                      shown.toLocaleString() + " highest-risk. Zoom in to see the rest."
                    : "");
            }

            var debounceTimer = null;
            function debouncedUpdate() {
                clearTimeout(debounceTimer);
                debounceTimer = setTimeout(updateView, 120);
            }

            map.on("zoomend moveend", debouncedUpdate);
            updateView();
        })();
        """

        client_side_script = (
            client_side_script_template
            .replace("__MAP__", map_variable)
            .replace("__GRID__", grid_variable)
            # "</" is escaped so a stray "</script>" in a label can never end the script block.
            .replace("__DATA__", json.dumps(map_data).replace("</", "<\\/"))
            .replace("__ZOOM__", str(ZOOM_SWITCH_LEVEL))
            .replace("__MAX_MARKERS__", str(MAX_MARKERS_IN_VIEW))
            .replace("__TIER_COLORS__", json.dumps([tier_colors[tier] for tier in tier_order]))
            .replace("__TIER_NAMES__", json.dumps(tier_order))
        )

        # MacroElement/Template renders this script inside the map's own
        # <script> block via branca's templating, rather than injecting a
        # raw <script> tag into the page body.
        class SafeCrossMapScript(MacroElement):
            def __init__(self, script: str):
                super().__init__()
                self._name = "SafeCrossMapScript"
                self.script = script
                self._template = Template(
                    """
                {% macro script(this, kwargs) %}
                {{ this.script | safe }}
                {% endmacro %}
                """
                )

        risk_map.add_child(SafeCrossMapScript(client_side_script))

        # returned_objects=[] and a stable key: st_folium does not send
        # bounds/zoom/center back to Python on pan/zoom, so moving the map
        # never triggers a Streamlit rerun in the first place.
        st_folium(risk_map, width=None, height=700, key="safecross_map", returned_objects=[])
    else:
        st.info("No location data available to plot for this filter.")

    # --- Flagged intersections table (paginated) + explanation panel ----
    st.subheader("Flagged intersections")

    # Load the table incrementally instead of rendering every row at once -
    # the full dataset stays available, just not all rendered up front.
    # Resets back to one page whenever the active filters change, so "load
    # more" always means "more of THIS filter", not stale rows from a
    # previous selection.
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

    if selected_label and len(filtered_rows) > 0:
        st.divider()
        st.subheader(f"Explanation: {selected_label}")

        selected_row = filtered_rows.loc[filtered_rows["intersection_label"] == selected_label].iloc[0]

        explanation_columns = st.columns(3)
        explanation_columns[0].metric("Relative risk", selected_row["risk_tier"])
        explanation_columns[1].metric("Percentile", f"{selected_row['risk_percentile']:.1f}")
        if "crashes_last_4w" in selected_row:
            explanation_columns[2].metric("Crashes, last 4 weeks", int(selected_row["crashes_last_4w"]))

        signals = top_signals_for_row(selected_row, signal_features, reference=week_rows)
        if signals:
            st.markdown("**Top model signals for this intersection:**")
            for feature, value, percentile in signals:
                detail = f" (higher than {int(percentile * 100)}% of intersections in this snapshot)" if percentile is not None else ""
                st.write(f"- {feature.replace('_', ' ')}: {value:.4g}{detail}")

        st.markdown("**Candidate safety-review areas** *(rule-based suggestions, not a model output):*")
        for measure in candidate_measures_for_row(selected_row):
            st.write(f"- {measure}")

        st.caption(
            "These are starting points for further review, not engineering "
            "recommendations. The model cannot prove any location is "
            "dangerous - only that it resembles ones that had a crash the "
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
        "enough that a specific percentage would overstate precision - so "
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
        st.caption("No saved test metrics found - this section is optional and skipped.")

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
  from the model rather than guessed at - see Notebook 2's feature audit.
- **Long history, one present-day street map.** The model learns from crash
  history going back to 2012, but intersection and road-design data come from
  today's OpenStreetMap. A redesigned intersection may not match the layout that
  existed when its older crashes happened, and crash reporting and geocoding
  practices also changed over those years.
- **Weather is one citywide location.** Weather features come from the weather
  stations nearest Central Park and are identical for every intersection in a
  given week, so they cannot explain why one intersection ranks above another.
- **Time-based testing.** Validation and test use the most recent weeks, so
  results may differ for other periods (for example, before versus after
  COVID-era traffic changes).
- **Feature importance is not causation.** It shows what the model relies
  on, not what causes crashes. Many flagged locations simply have more
  recent crash activity - that's a reason for follow-up, not proof of danger.
- **Candidate safety measures are not recommendations.** They are simple,
  transparent rules meant to give a reviewer a starting point. Every flagged
  location needs site review and external road-safety evidence before any
  action is taken.
        """
    )