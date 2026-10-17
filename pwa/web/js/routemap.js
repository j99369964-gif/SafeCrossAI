// Draws a route result on the shared Google Map: one line per route, start/end markers, and a dot for every
// intersection the routes pass, coloured by risk tier exactly like the Explore map. Dots and markers are drawn on one
// canvas (see canvaslayer.js) so the map stays smooth with hundreds of them. Clicking a dot (or a route line) is
// reported to the caller, which shows the details panel.
import { h, reducedMotion } from "./dom.js";
import { mapIsDark } from "./gmaps.js";
import { TIER_COLORS } from "./detail.js";
import { createCanvasLayer } from "./canvaslayer.js";

const DOT_PIXELS = [7, 6, 5, 5];

export function createTripMap({ maps, map, trip, onSelectRoute, onSelectNode }) {
  const data = trip.map;
  const info = new maps.InfoWindow();
  const bounds = new maps.LatLngBounds();
  const lines = [];
  const casings = [];
  const dots = new Map(); // intersection id -> dot
  const listeners = [];
  let highlighted = -1;
  let visibleTiers = new Set([0, 1]);
  let selectedId = null;

  const openInfo = (position, text) => {
    info.setContent(h("div", { style: "font-size:13px;font-weight:bold;color:#1b1f24" }, text));
    info.setPosition(position);
    info.open(map);
  };

  // Each route is a coloured line on a slightly wider casing in the map's background colour, so overlapping routes and
  // busy streets don't swallow it.
  const casingColor = mapIsDark() ? "#111214" : "#ffffff";
  const paths = data.routes.map((route) => route.points.map(([lat, lng]) => ({ lat, lng })));
  paths.forEach((path, index) => {
    path.forEach((point) => bounds.extend(point));
    const casing = new maps.Polyline({ path, strokeColor: casingColor, strokeOpacity: 0.9, strokeWeight: 9, zIndex: 0, clickable: false, map });
    const line = new maps.Polyline({ path, strokeColor: data.routes[index].color, strokeOpacity: 0.85, strokeWeight: 5, zIndex: 1, map });
    // A dot lying on the line gets the click first: the line would otherwise swallow it.
    listeners.push(line.addListener("click", (event) => {
      const hit = layer.hitTest(event.latLng);
      if (hit) handleHit(hit); else if (onSelectRoute) onSelectRoute(index);
    }));
    casings.push(casing);
    lines.push(line);
  });

  // Draw the lines from start to end once, as if traced. Skipped when the user prefers reduced motion.
  let drawFrame = 0;
  function drawIn(duration = 1100) {
    if (reducedMotion()) return;
    const started = performance.now();
    const step = (now) => {
      const t = Math.min(1, (now - started) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      paths.forEach((path, index) => {
        const part = path.slice(0, Math.max(2, Math.ceil(path.length * eased)));
        lines[index].setPath(part);
        casings[index].setPath(part);
      });
      if (t < 1) drawFrame = requestAnimationFrame(step);
    };
    drawFrame = requestAnimationFrame(step);
  }

  function handleHit(hit) {
    if (hit.data.endpoint) openInfo(hit.data.position, hit.data.endpoint);
    else { info.close(); if (onSelectNode) onSelectNode(hit.data.id); }
  }
  const layer = createCanvasLayer(maps, map, { onClick: handleHit });

  const endpoints = [["Start", data.start, "#f5b301"], ["End", data.end, "#17191b"]].map(([name, [lat, lng], color]) => ({
    lat, lng, r: 9, fill: color, stroke: "#ffffff", strokeWidth: 2, z: 100, data: { endpoint: name, position: { lat, lng } },
  }));
  data.dots.forEach((dot) => dots.set(dot.id, dot));

  function refreshDots() {
    const shown = [];
    dots.forEach((dot) => {
      const onFocusedRoute = highlighted < 0 || dot.routes.includes(data.routes[highlighted].label);
      if (!visibleTiers.has(dot.tier) || !onFocusedRoute) return;
      const selected = dot.id === selectedId;
      shown.push({
        lat: dot.lat, lng: dot.lng, r: DOT_PIXELS[dot.tier] || 5,
        fill: TIER_COLORS[dot.tier], alpha: dot.unvalidated ? 0.55 : 0.95,
        stroke: selected ? "#000000" : "#ffffff", strokeWidth: selected ? 3 : 1,
        z: selected ? 50 : 10 - dot.tier, data: { id: dot.id },
      });
    });
    layer.setDots([...shown, ...endpoints]);
  }

  function highlight(index) {
    highlighted = index;
    lines.forEach((line, k) => line.setOptions({
      strokeWeight: index < 0 ? 5 : k === index ? 8 : 4,
      strokeOpacity: index < 0 ? 0.85 : k === index ? 1 : 0.35,
      zIndex: k === index ? 3 : 1,
    }));
    casings.forEach((casing, k) => casing.setOptions({
      strokeWeight: index < 0 ? 9 : k === index ? 13 : 7,
      strokeOpacity: index < 0 || k === index ? 0.9 : 0.35,
      zIndex: k === index ? 2 : 0,
    }));
    refreshDots();
  }

  /** `tiers` is a Set of tier codes (0 = highest priority ... 3 = lower) that should be drawn. */
  function setTiers(tiers) {
    visibleTiers = new Set(tiers);
    refreshDots();
  }

  function selectNode(id) {
    selectedId = id;
    refreshDots();
  }

  /** Centre the map on one intersection and zoom in far enough to see the street around it. */
  function focusNode(id) {
    const dot = dots.get(id);
    if (!dot) return;
    map.panTo({ lat: dot.lat, lng: dot.lng });
    if (map.getZoom() < 16) map.setZoom(16);
  }

  function fit() {
    map.fitBounds(bounds, 40);
  }

  function destroy() {
    cancelAnimationFrame(drawFrame);
    info.close();
    listeners.forEach((listener) => listener.remove());
    layer.destroy();
    [...lines, ...casings].forEach((shape) => shape.setMap(null));
  }

  fit();
  refreshDots();
  drawIn();
  return { highlight, setTiers, selectNode, focusNode, fit, destroy };
}
