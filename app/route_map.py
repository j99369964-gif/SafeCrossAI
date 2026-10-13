"""Renders route options on a GOOGLE MAP (Maps JavaScript API).

Why this isn't Folium: Google's Routes API policy requires route results that are shown on a
map to be shown on a Google Map. The Explore page can keep using Folium because it shows
none of Google's data; the route page cannot.

Two different Google keys are used, on purpose:

* Routes API key  - server-side only (never sent to the browser).
* Maps JavaScript API key - sent to the visitor's browser, which is unavoidable for
  this API. Restrict it in Google Cloud Console to the Maps JavaScript API only and to your app's
  HTTP referrers, so it is useless for anything else.

The map is drawn once per search and is NOT re-created when the user picks a route in the
Streamlit controls, because every re-render would load the Google Maps JavaScript API again
(a billable map load). Highlighting a route happens inside the map instead.
"""

from __future__ import annotations

import json
import re
import urllib.parse

# Hidden test hook: the test suite reads this to extract the page's script.
MAP_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  html, body { height: 100%; margin: 0; font-family: Arial, Helvetica, sans-serif; }
  #map { height: 100%; width: 100%; }
  #status { display: none; position: absolute; top: 12px; left: 12px; right: 12px; z-index: 5;
            background: #fff3cd; color: #664d03; border: 1px solid #ffecb5; padding: 10px 12px;
            border-radius: 6px; font-size: 13px; }
  .sc-legend { background: #fff; margin: 10px; padding: 8px 10px; border-radius: 6px; font-size: 12px;
               box-shadow: 0 1px 4px rgba(0,0,0,0.3); max-width: 270px; line-height: 1.35; }
  .sc-chip { display: block; width: 100%; text-align: left; background: #fff; border: 2px solid #ccc; border-radius: 6px;
             padding: 4px 8px; margin: 3px 0; cursor: pointer; font-size: 12px; }
  .sc-chip.active { background: #f1f3f4; }
  .sc-swatch { display: inline-block; width: 18px; height: 4px; vertical-align: middle; margin-right: 6px; border-radius: 2px; }
  .sc-dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 5px; vertical-align: middle; border: 1px solid #fff; box-shadow: 0 0 0 1px #999; }
</style>
</head>
<body>
<div id="map"></div>
<div id="status"></div>
<script>
(function () {
  var DATA = __DATA__;
  var statusEl = document.getElementById("status");
  function showError(message) { statusEl.style.display = "block"; statusEl.textContent = message; }

  // Called by Google if the browser key is rejected (disabled API, wrong referrer, billing...).
  window.gm_authFailure = function () {
    showError("Google Maps rejected the browser API key. Check that the Maps JavaScript API is enabled, " +
              "billing is on, and the key's HTTP-referrer restrictions include this site.");
  };
  // If the script never loads (network, blocked, bad key format) say so instead of a blank box.
  setTimeout(function () {
    if (!(window.google && window.google.maps)) {
      showError("Google Maps did not load. Check your connection and the Maps JavaScript API key.");
    }
  }, 12000);

  window.initMap = function () {
    var maps = google.maps;
    var map = new maps.Map(document.getElementById("map"), {
      center: { lat: DATA.center[0], lng: DATA.center[1] }, zoom: 12,
      mapTypeControl: false, streetViewControl: false, clickableIcons: false, fullscreenControl: true
    });
    var info = new maps.InfoWindow();
    var bounds = new maps.LatLngBounds();
    var cosLat = Math.cos(DATA.center[0] * Math.PI / 180);
    // Metres covered by `px` screen pixels at this zoom, so dots stay a constant on-screen size.
    function metersFor(zoom, px) { return px * 156543.03392 * cosLat / Math.pow(2, zoom); }

    var highlighted = -1;
    var showElevated = false;
    var lines = [], chips = [], dotObjects = [], endpointObjects = [];

    function text(tag, content, style) {
      var el = document.createElement(tag);
      el.textContent = content;
      if (style) { el.style.cssText = style; }
      return el;
    }
    function openInfo(position, lines_) {
      var box = document.createElement("div");
      box.style.cssText = "font-size:13px;line-height:1.4;max-width:240px;";
      lines_.forEach(function (entry, i) { box.appendChild(text("div", entry, i === 0 ? "font-weight:bold;" : "")); });
      info.setContent(box);
      info.setPosition(position);
      info.open(map);
    }

    DATA.routes.forEach(function (route, i) {
      var path = route.points.map(function (p) { return { lat: p[0], lng: p[1] }; });
      path.forEach(function (p) { bounds.extend(p); });
      var line = new maps.Polyline({ path: path, strokeColor: route.color, strokeOpacity: 0.85, strokeWeight: 5, zIndex: 1, map: map });
      line.addListener("click", function () { setHighlight(i === highlighted ? -1 : i); });
      lines.push(line);
    });

    [["Start", DATA.start, "#188038"], ["End", DATA.end, "#202124"]].forEach(function (entry) {
      var position = { lat: entry[1][0], lng: entry[1][1] };
      var circle = new maps.Circle({ center: position, radius: metersFor(12, 9), fillColor: entry[2], fillOpacity: 1,
                                     strokeColor: "#ffffff", strokeWeight: 2, zIndex: 20, map: map });
      circle.addListener("click", function () { openInfo(position, [entry[0]]); });
      endpointObjects.push(circle);
    });

    DATA.dots.forEach(function (dot) {
      var position = { lat: dot.lat, lng: dot.lng };
      var px = dot.tier === 0 ? 6 : 4.5;
      var circle = new maps.Circle({
        center: position, radius: metersFor(12, px), fillColor: dot.tier === 0 ? "#d7191c" : "#fdae61", fillOpacity: 0.95,
        strokeColor: "#ffffff", strokeWeight: 1, zIndex: dot.tier === 0 ? 10 : 9, map: map
      });
      circle.addListener("click", function () {
        openInfo(position, [
          dot.label,
          dot.tier === 0 ? "Highest-priority (top 10%)" : "Elevated relative risk",
          dot.pct === null ? "" : "Relative risk percentile: " + dot.pct + "th",
          dot.unvalidated ? "Unvalidated estimate (road design only)" : "",
          "On: " + dot.routes.join(", ")
        ].filter(Boolean));
      });
      dotObjects.push({ dot: dot, circle: circle, px: px });
    });

    function refreshDots() {
      dotObjects.forEach(function (o) {
        var onHighlighted = highlighted < 0 || o.dot.routes.indexOf(DATA.routes[highlighted].label) >= 0;
        var visible = (o.dot.tier === 0 || showElevated) && onHighlighted;
        o.circle.setMap(visible ? map : null);
      });
    }
    function setHighlight(i) {
      highlighted = i;
      lines.forEach(function (line, k) {
        line.setOptions({ strokeWeight: i < 0 ? 5 : (k === i ? 8 : 4), strokeOpacity: i < 0 ? 0.85 : (k === i ? 1 : 0.35), zIndex: k === i ? 3 : 1 });
      });
      chips.forEach(function (chip, k) { chip.className = "sc-chip" + (k === i ? " active" : ""); });
      refreshDots();
    }
    function rescale() {
      var zoom = map.getZoom();
      dotObjects.forEach(function (o) { o.circle.setRadius(metersFor(zoom, o.px)); });
      endpointObjects.forEach(function (c) { c.setRadius(metersFor(zoom, 9)); });
    }
    map.addListener("zoom_changed", rescale);

    // --- Legend / controls (inside the map) ---
    var legend = document.createElement("div");
    legend.className = "sc-legend";
    legend.appendChild(text("div", "Click a route to focus it", "font-weight:bold;margin-bottom:3px;"));
    DATA.routes.forEach(function (route, i) {
      var chip = document.createElement("button");
      chip.type = "button";
      chip.className = "sc-chip";
      chip.style.borderColor = route.color;
      var swatch = document.createElement("span");
      swatch.className = "sc-swatch";
      swatch.style.background = route.color;
      chip.appendChild(swatch);
      chip.appendChild(text("span", route.label + ": " + route.minutes + " min, " + route.high + " high-risk"));
      chip.addEventListener("click", function () { setHighlight(i === highlighted ? -1 : i); });
      chips.push(chip);
      legend.appendChild(chip);
    });
    var keyRow = document.createElement("div");
    keyRow.style.marginTop = "6px";
    var redDot = document.createElement("span"); redDot.className = "sc-dot"; redDot.style.background = "#d7191c";
    keyRow.appendChild(redDot); keyRow.appendChild(text("span", "Highest-priority intersection"));
    legend.appendChild(keyRow);
    var elevatedRow = document.createElement("label");
    elevatedRow.style.cssText = "display:block;margin-top:4px;cursor:pointer;";
    var checkbox = document.createElement("input"); checkbox.type = "checkbox";
    checkbox.addEventListener("change", function () { showElevated = checkbox.checked; refreshDots(); });
    var orangeDot = document.createElement("span"); orangeDot.className = "sc-dot"; orangeDot.style.background = "#fdae61"; orangeDot.style.marginLeft = "4px";
    elevatedRow.appendChild(checkbox); elevatedRow.appendChild(orangeDot); elevatedRow.appendChild(text("span", "Also show elevated-risk"));
    legend.appendChild(elevatedRow);
    if (DATA.hasUnvalidated) {
      legend.appendChild(text("div", "Dots marked 'unvalidated' are in an area with no crash history, so they are ranked on road design alone.",
                              "margin-top:6px;font-style:italic;color:#555;"));
    }
    map.controls[maps.ControlPosition.TOP_LEFT].push(legend);

    map.fitBounds(bounds, 40);
    refreshDots();
  };
})();
</script>
<script async src="https://maps.googleapis.com/maps/api/js?key=__KEY__&callback=initMap&loading=async&v=weekly"></script>
</body>
</html>
"""

_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_\-]{10,200}$")


def build_route_map_html(js_api_key: str, payload: dict) -> str:
    """Return the full HTML page for the map. Raises ValueError for a malformed key."""
    key = (js_api_key or "").strip()
    if not _KEY_PATTERN.match(key):
        raise ValueError("The Google Maps JavaScript API key looks malformed (unexpected characters or length).")
    # "<" is escaped so nothing in the data can ever close the <script> block early.
    data_json = json.dumps(payload, separators=(",", ":")).replace("<", "\\u003c")
    return MAP_HTML_TEMPLATE.replace("__DATA__", data_json).replace("__KEY__", urllib.parse.quote(key, safe=""))


def render_route_map(js_api_key: str, payload: dict, height: int = 560) -> None:
    """Draw the Google Map inside the Streamlit page."""
    import streamlit.components.v1 as components  # imported lazily so this module is testable without Streamlit

    components.html(build_route_map_html(js_api_key, payload), height=height)
