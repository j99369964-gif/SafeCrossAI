from __future__ import annotations

import json
import sys
from pathlib import Path

import branca.colormap
from branca.element import MacroElement, Template
import folium
import streamlit as st
from streamlit_folium import st_folium

# Allow "from app_utils import ..." to work correctly
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app_utils import (
    assign_risk_tier,
    build_risk_grid,
    format_intersection_label,
    load_demo_data,
    load_model_bundle,
    predict_risk,
)

st.set_page_config(page_title="SafeCross AI - Map", layout="wide")
st.title("SafeCross AI - Explanable road-safety screening for urban intersections")


# --- 1. Load Data --------------------------------------------------------
bundle = load_model_bundle()
demo_data = load_demo_data()

demo_data = demo_data.copy()
demo_data["predicted_probability"] = predict_risk(bundle, demo_data)
demo_data["risk_tier"] = assign_risk_tier(demo_data["predicted_probability"])
demo_data["intersection_label"] = demo_data.apply(format_intersection_label, axis=1)

# --- 2. Build Filters ----------------------------------------------------
tier_options = [
    "Highest-priority (top 10%)", 
    "Elevated relative risk", 
    "Moderate relative risk", 
    "Lower relative risk"
]
selected_tiers = st.multiselect("Filter by relative risk tier", tier_options, default=tier_options)

filtered_rows = demo_data.loc[demo_data["risk_tier"].isin(selected_tiers)].sort_values(
    "predicted_probability", ascending=False
)

selected_label = st.selectbox(
    "Select an intersection to highlight (optional)",
    options=[None] + filtered_rows["intersection_label"].tolist(),
    index=0
)

# --- 3. Render Map -------------------------------------------------------
class SafeCrossMapScript(MacroElement):
    def __init__(self, script: str):
        super().__init__()
        self._name = "SafeCrossMapScript"
        self.script = script
        self._template = Template("""
    {% macro script(this, kwargs) %}
    {{ this.script | safe }}
    {% endmacro %}
    """)
if len(filtered_rows) > 0 and {"latitude", "longitude"}.issubset(filtered_rows.columns):
    map_center = [filtered_rows["latitude"].median(), filtered_rows["longitude"].median()]

    ZOOM_SWITCH_LEVEL = 14

    risk_map = folium.Map(
        location=map_center,
        zoom_start=ZOOM_SWITCH_LEVEL - 3,
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

    grid_layer = folium.FeatureGroup(name="Area risk", show=True)

    risk_grid = build_risk_grid(filtered_rows)
    probabilities = [feature["properties"]["mean_probability"] for feature in risk_grid["features"]]

    if probabilities:
        color_scale = branca.colormap.LinearColormap(
            colors=["#f0f0f0", "#fdae61", "#d7191c"],
            vmin=min(probabilities),
            vmax=max(probabilities),
        ).to_step(6)

        # Python function condensed to one line
        def style_grid_cell(feature: dict) -> dict: return {"fillColor": color_scale(feature["properties"]["mean_probability"]), "color": "#888888", "weight": 0.5, "fillOpacity": 0.65}

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

    node_points = [
        {
            "lat": row["latitude"],
            "lng": row["longitude"],
            "color": tier_colors.get(row["risk_tier"], "gray"),
            "label": f"{row['intersection_label']} — {row['risk_tier']}",
            "selected": row["intersection_label"] == selected_label,
        }
        for _, row in filtered_rows.iterrows()
    ]

    map_variable = risk_map.get_name()
    grid_variable = grid_layer.get_name()

    client_side_script = f"""
    (function() {{
        var safecrossPoints = {json.dumps(node_points)};
        var safecrossZoomSwitch = {ZOOM_SWITCH_LEVEL};
        var safecrossMarkerLayer = L.layerGroup();
        var safecrossActiveMarkers = {{}};

        function safecrossUpdateView() {{
            if ({map_variable}.getZoom() < safecrossZoomSwitch) {{
                safecrossMarkerLayer.clearLayers();
                safecrossActiveMarkers = {{}};
                if ({map_variable}.hasLayer(safecrossMarkerLayer)) {map_variable}.removeLayer(safecrossMarkerLayer);
                if (!{map_variable}.hasLayer({grid_variable})) {map_variable}.addLayer({grid_variable});
                return;
            }}

            if ({map_variable}.hasLayer({grid_variable})) {map_variable}.removeLayer({grid_variable});
            if (!{map_variable}.hasLayer(safecrossMarkerLayer)) safecrossMarkerLayer.addTo({map_variable});

            var bounds = {map_variable}.getBounds();
            var stillVisible = {{}};

            for (var i = 0; i < safecrossPoints.length; i++) {{
                var p = safecrossPoints[i];
                if (bounds.contains([p.lat, p.lng])) {{
                    stillVisible[i] = true;
                    if (!safecrossActiveMarkers[i]) {{
                        var marker = L.circleMarker([p.lat, p.lng], {{radius: p.selected ? 7 : 6, color: p.color, fillColor:p.color, fill: true, fillOpacity: 0.9,weight: p.selected ? 3 : 1}}).bindTooltip(p.label);
                        marker.addTo(safecrossMarkerLayer);
                        safecrossActiveMarkers[i] = marker;
                    }}
                }}
            }}

            for (var key in safecrossActiveMarkers) {{
                if (!stillVisible[key]) {{
                    safecrossMarkerLayer.removeLayer(safecrossActiveMarkers[key]);
                    delete safecrossActiveMarkers[key];
                }}
            }}
        }}

        var safecrossDebounceTimer = null;
        function safecrossDebouncedUpdate() {{
            clearTimeout(safecrossDebounceTimer);
            safecrossDebounceTimer = setTimeout(safecrossUpdateView, 120);
        }}

        {map_variable}.on("zoomend moveend", safecrossDebouncedUpdate);
        safecrossUpdateView();
    }})();
    """
    
    risk_map.add_child(SafeCrossMapScript(client_side_script))
    st_folium(risk_map, width=None, height=700, key="safecross_map", returned_objects=[])
else:
    st.info("No location data available to plot for this filter.")
