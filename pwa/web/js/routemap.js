// Draws a route result on the shared Google Map: one line per route, start/end markers, and a dot for every
// intersection the routes pass, coloured by risk tier exactly like the Explore map. Dots keep a constant on-screen
// size. Clicking a dot (or a route line) is reported to the caller, which shows the details panel.
import { h, reducedMotion } from "./dom.js";
import { metersForPixels, mapIsDark } from "./gmaps.js";
import { TIER_COLORS } from "./detail.js";

const DOT_PIXELS = [7, 6, 5, 5];

export function createTripMap({ maps, map, trip, onSelectRoute, onSelectNode }) {
  const data = trip.map;
  const info = new maps.InfoWindow();
  const bounds = new maps.LatLngBounds();
  const lines = [];
  const casings = [];
  const dots = new Map(); // intersection id -> { dot, circle, pixels }
  const endpoints = [];
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
    listeners.push(line.addListener("click", () => onSelectRoute && onSelectRoute(index)));
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

  [["Start", data.start, "#f5b301"], ["End", data.end, "#17191b"]].forEach(([name, [lat, lng], color]) => {
    const position = { lat, lng };
    const circle = new maps.Circle({ center: position, radius: metersForPixels(map, 9), fillColor: color, fillOpacity: 1, strokeColor: "#ffffff", strokeWeight: 2, zIndex: 20, map });
    listeners.push(circle.addListener("click", () => openInfo(position, name)));
    endpoints.push(circle);
  });

  data.dots.forEach((dot) => {
    const pixels = DOT_PIXELS[dot.tier] || 5;
    const circle = new maps.Circle({
      center: { lat: dot.lat, lng: dot.lng }, radius: metersForPixels(map, pixels), map,
      fillColor: TIER_COLORS[dot.tier], fillOpacity: dot.unvalidated ? 0.55 : 0.95,
      strokeColor: "#ffffff", strokeWeight: 1, zIndex: 10 - dot.tier,
    });
    listeners.push(circle.addListener("click", () => { info.close(); onSelectNode && onSelectNode(dot.id); }));
    dots.set(dot.id, { dot, circle, pixels });
  });

  function styleDot({ dot, circle }) {
    const selected = dot.id === selectedId;
    circle.setOptions({
      strokeColor: selected ? "#000000" : "#ffffff", strokeWeight: selected ? 3 : 1,
      zIndex: selected ? 50 : 10 - dot.tier,
    });
  }

  function refreshDots() {
    dots.forEach((entry) => {
      const { dot, circle } = entry;
      const onFocusedRoute = highlighted < 0 || dot.routes.includes(data.routes[highlighted].label);
      circle.setMap(visibleTiers.has(dot.tier) && onFocusedRoute ? map : null);
      styleDot(entry);
    });
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

  function rescale() {
    dots.forEach(({ circle, pixels }) => circle.setRadius(metersForPixels(map, pixels)));
    endpoints.forEach((circle) => circle.setRadius(metersForPixels(map, 9)));
  }
  listeners.push(map.addListener("zoom_changed", rescale));

  /** `tiers` is a Set of tier codes (0 = highest priority ... 3 = lower) that should be drawn. */
  function setTiers(tiers) {
    visibleTiers = new Set(tiers);
    refreshDots();
  }

  function selectNode(id) {
    selectedId = id;
    dots.forEach(styleDot);
  }

  /** Centre the map on one intersection and zoom in far enough to see the street around it. */
  function focusNode(id) {
    const entry = dots.get(id);
    if (!entry) return;
    map.panTo({ lat: entry.dot.lat, lng: entry.dot.lng });
    if (map.getZoom() < 16) map.setZoom(16);
  }

  function fit() {
    map.fitBounds(bounds, 40);
  }

  function destroy() {
    cancelAnimationFrame(drawFrame);
    info.close();
    listeners.forEach((listener) => listener.remove());
    [...lines, ...casings, ...endpoints, ...[...dots.values()].map((entry) => entry.circle)].forEach((shape) => shape.setMap(null));
  }

  fit();
  refreshDots();
  drawIn();
  return { highlight, setTiers, selectNode, focusNode, fit, destroy };
}
