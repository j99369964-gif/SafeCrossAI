"""SafeCross AI — Streamlit Map Only."""
from __future__ import annotations

import sys
from pathlib import Path

import branca.colormap
import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

# Allow "from app_utils import ..." from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app_utils import (assign_risk_tier, build_risk_grid, format_intersection_label, load_demo_data, load_model_bundle, predict_risk)  # noqa: E402

st.set_page_config(page_title="SafeCross AI Map", layout="wide")

# --- Load only what is needed for the map --------
bundle = load_model_bundle()
demo_data = load_demo_data().copy()

# --- Run inference -------------------------------
demo_data["predicted_probability"] = predict_risk(bundle, demo_data)
demo_data["risk_tier"] = assign_risk_tier(demo_data["predicted_probability"])

# =========================== MAP VIEW ==================================
week_options = sorted(demo_data["week_start"].unique().tolist()) if "week_start" in demo_data.columns else []
if week_options:
    selected_week = st.selectbox("Select Week", week_options, index=len(week_options) - 1)
    week_rows = demo_data.loc[demo_data["week_start"] == selected_week].copy()
else:
    week_rows = demo_data.copy()

week_rows["intersection_label"] = week_rows.apply(format_intersection_label, axis=1)

tier_options = ["Highest-priority (top 10%)", "Elevated relative risk", "Moderate relative risk", "Lower relative risk"]
selected_tiers = st.multiselect("Select Risk Filters", tier_options, default=tier_options)
filtered_rows = week_rows.loc[week_rows["risk_tier"].isin(selected_tiers)].sort_values("predicted_probability", ascending=False)

st.subheader("Map")

if len(filtered_rows) > 0 and {"latitude", "longitude"}.issubset(filtered_rows.columns):
    
    if "map_center" not in st.session_state:
        st.session_state.map_center = [filtered_rows["latitude"].median(), filtered_rows["longitude"].median()]
    if "map_zoom" not in st.session_state:
        st.session_state.map_zoom = 11
    if "map_bounds" not in st.session_state:
        st.session_state.map_bounds = None

    risk_map = folium.Map(location=st.session_state.map_center, zoom_start=st.session_state.map_zoom, tiles="cartodbpositron")

    tier_colors = {"Highest-priority (top 10%)": "red", "Elevated relative risk": "orange", "Moderate relative risk": "blue", "Lower relative risk": "gray"}

    risk_grid = build_risk_grid(filtered_rows)
    probabilities = [feature["properties"]["mean_probability"] for feature in risk_grid.get("features", [])]
    
    bounds = st.session_state.map_bounds
    visible_grid_count = 0
    
    if bounds and risk_grid.get("features"):
        south, north, west, east = bounds["_southWest"]["lat"], bounds["_northEast"]["lat"], bounds["_southWest"]["lng"], bounds["_northEast"]["lng"]
        for feature in risk_grid["features"]:
            coords = feature["geometry"]["coordinates"][0]
            lats, lons = [c[1] for c in coords], [c[0] for c in coords]
            if not (max(lats) < south or min(lats) > north or max(lons) < west or min(lons) > east):
                visible_grid_count += 1
    
    zoomed_in_enough = (visible_grid_count > 0 and visible_grid_count <= 9)

    if not zoomed_in_enough and probabilities:
        grid_layer = folium.FeatureGroup(name="Area risk", show=True)
        color_scale = branca.colormap.LinearColormap(colors=["#f0f0f0", "#fdae61", "#d7191c"], vmin=min(probabilities), vmax=max(probabilities)).to_step(6)
        
        def style_grid_cell(feature: dict) -> dict: return {"fillColor": color_scale(feature["properties"]["mean_probability"]), "color": "#888888", "weight": 0.5, "fillOpacity": 0.65}
        
        folium.GeoJson(risk_grid, style_function=style_grid_cell, tooltip=folium.GeoJsonTooltip(fields=["dominant_tier", "point_count"], aliases=["Dominant risk tier", "Intersections in area"])).add_to(grid_layer)
        color_scale.caption = "Mean predicted risk (area average)"
        color_scale.add_to(risk_map)
        grid_layer.add_to(risk_map)

    if zoomed_in_enough and bounds:
        node_layer = folium.FeatureGroup(name="Intersections", show=True)
        in_view_rows = filtered_rows.loc[filtered_rows["latitude"].between(south, north) & filtered_rows["longitude"].between(west, east)]

        for _, row in in_view_rows.iterrows():
            folium.CircleMarker(location=[row["latitude"], row["longitude"]], radius=4, color=tier_colors.get(row["risk_tier"], "gray"), fill=True, fill_opacity=0.8, tooltip=f"{row['intersection_label']} — {row['risk_tier']}").add_to(node_layer)

        node_layer.add_to(risk_map)
        st.caption(f"{len(in_view_rows):,} intersections rendered in the current view.")

    map_state = st_folium(risk_map, width=None, height=600, returned_objects=["bounds", "zoom", "center"])

    if map_state:
        if map_state.get("bounds"): st.session_state.map_bounds = map_state["bounds"]
        if map_state.get("zoom") is not None: st.session_state.map_zoom = map_state["zoom"]
        if map_state.get("center"): st.session_state.map_center = [map_state["center"]["lat"], map_state["center"]["lng"]]
else:
    st.info("No location data available to plot for this filter.")