// 3D crash history: OBSERVED crashes, aggregated into H3 hexagons on the server, drawn as one extruded column per
// hexagon with deck.gl on a MapLibre base map (the Google map in this app is a raster map and can't tilt).
//
// Why columns and not points: years of crashes drawn one marker each pile on top of each other until the map is a
// blob. Aggregating means a longer period makes columns taller, never the map busier.
//
// Height and colour are proportional to the count up to the 99th percentile, and the busiest 1% are drawn at that cap,
// so a handful of extreme hexagons don't dwarf everything else. (A log scale was tried first: it squashed the median
// hexagon to ~45% of the tallest, a flat carpet with no visible concentrations.) Tooltips and the list under the map
// always show the real counts. The libraries are loaded only when this view is first opened.
import { h, reducedMotion } from "./dom.js";
import { TIER_COLORS } from "./detail.js";

const LIBS = {
  css: "https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css",
  maplibre: "https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js",
  h3: "https://unpkg.com/h3-js@4.1.0/dist/h3-js.umd.js", // deck.gl's bundle reads h3-js from window.h3, so it loads first
  deck: "https://unpkg.com/deck.gl@9.1.14/dist.min.js", // H3HexagonLayer and MapboxOverlay
};
// Free CARTO base maps (no key). Attribution is shown by MapLibre's attribution control.
const STYLES = {
  light: "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
  dark: "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
};
const LOAD_TIMEOUT_MS = 20000;

export const METRICS = [
  { key: "all", label: "All crashes", noun: "Crashes" },
  { key: "injury", label: "Injury crashes", noun: "Injury crashes", hint: "someone injured or killed" },
  { key: "pedestrian", label: "Pedestrian-involved", noun: "Pedestrian injured or killed", hint: "a pedestrian injured or killed" },
  { key: "cyclist", label: "Cyclist-involved", noun: "Cyclist injured or killed", hint: "a cyclist injured or killed" },
];

/** Column height, in metres, at the 99th-percentile cap. */
const MAX_HEIGHT_M = 1400;
const CAP_PERCENTILE = 0.99;

// Level of detail: full 3D columns at city scale, flattening into 2D density cells by neighbourhood scale, where the
// SafeCross rings take over. Tall columns at street level would only hide the streets and the rings.
const FULL_HEIGHT_ZOOM = 12.5;
const FLAT_ZOOM = 14.5;
export function heightFactor(zoom) {
  const t = (FLAT_ZOOM - zoom) / (FLAT_ZOOM - FULL_HEIGHT_ZOOM);
  return Math.max(0.015, Math.min(1, t));
}

// A sequential ramp (deep blue -> teal -> pale yellow) kept clear of the risk tiers' red/orange, so observed history
// and the model's rings never read as the same thing.
const RAMP = [[37, 52, 148], [44, 127, 184], [65, 182, 196], [161, 218, 180], [255, 255, 204]];
export const RAMP_CSS = `linear-gradient(90deg, ${RAMP.map((c) => `rgb(${c.join(",")})`).join(", ")})`;

export function rampColor(t) {
  const v = Math.max(0, Math.min(1, t)) * (RAMP.length - 1);
  const i = Math.min(Math.floor(v), RAMP.length - 2);
  const f = v - i;
  return RAMP[i].map((channel, k) => Math.round(channel + (RAMP[i + 1][k] - channel) * f));
}

/** Linear scale capped at the 99th percentile of the non-zero counts: 0 -> 0, the cap and above -> 1. */
export function cappedScale(values) {
  const sorted = values.filter((v) => v > 0).sort((a, b) => a - b);
  const cap = Math.max(1, sorted.length ? sorted[Math.min(sorted.length - 1, Math.floor(CAP_PERCENTILE * sorted.length))] : 1);
  return { cap, scale: (value) => Math.min(1, Math.max(0, value) / cap) };
}

const hexToRgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));

let libsPromise = null;
function loadScript(src) {
  return new Promise((resolve, reject) => {
    const script = h("script", { src, async: true, crossorigin: "anonymous" });
    script.onload = resolve;
    script.onerror = () => reject(new Error("The 3D map libraries couldn't be loaded. Check your connection and try again."));
    document.head.append(script);
  });
}
export function loadHistoryLibraries() {
  if (window.deck && window.maplibregl && window.h3) return Promise.resolve();
  if (libsPromise) return libsPromise;
  if (!document.querySelector(`link[href="${LIBS.css}"]`)) document.head.append(h("link", { rel: "stylesheet", href: LIBS.css }));
  const timeout = new Promise((_, reject) => setTimeout(() => reject(new Error("The 3D map took too long to load. Check your connection.")), LOAD_TIMEOUT_MS));
  libsPromise = Promise.race([Promise.all([loadScript(LIBS.maplibre), loadScript(LIBS.h3).then(() => loadScript(LIBS.deck))]), timeout])
    .catch((problem) => { libsPromise = null; throw problem; });
  return libsPromise;
}

const darkQuery = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
const isDark = () => Boolean(darkQuery && darkQuery.matches);

function webglAvailable() {
  try { const canvas = document.createElement("canvas"); return Boolean(canvas.getContext("webgl2") || canvas.getContext("webgl")); }
  catch { return false; }
}

/**
 * Creates the 3D map in `container`. `onRing(id)` runs when a SafeCross ring is clicked; `onMove(bounds)` after the
 * camera stops. Returns { setHexes, setMetric, setRings, resize, bounds, destroy }.
 */
export async function mountHistoryMap(container, { onRing, onMove }) {
  if (!webglAvailable()) throw new Error("The 3D view needs WebGL, which this browser or device has turned off. The SafeCross risk map still works.");
  await loadHistoryLibraries();
  const { maplibregl, deck } = window;
  const motion = !reducedMotion();

  const map = new maplibregl.Map({
    container,
    style: isDark() ? STYLES.dark : STYLES.light,
    center: [-73.968, 40.742], // Midtown, with the avenues running up the screen (Manhattan's grid is ~29 degrees off north)
    zoom: 11.6,
    pitch: 50,
    bearing: 29,
    maxPitch: 70,
    attributionControl: { compact: true },
    dragRotate: true,
    touchPitch: true,
  });
  map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");

  let hexes = [];
  let metric = "all";
  let scale = () => 0;
  let cap = 1;
  let period = "";
  let rings = [];

  const tooltip = ({ object, layer }) => {
    if (!object) return null;
    const style = { background: "rgba(17,18,20,.94)", color: "#ece8de", fontSize: "12.5px", lineHeight: "1.45", padding: "9px 11px", borderRadius: "10px", maxWidth: "260px" };
    if (layer.id === "rings") return { text: `${object.label || "SafeCross intersection"}\nSafeCross: highest-priority (top 10%) nearby\nClick for details`, style };
    const lines = [
      object.borough ? `${object.borough} · hexagon of about 0.1 km²` : "Hexagon of about 0.1 km²",
      ...METRICS.map((m) => `${m.noun}: ${object[m.key].toLocaleString()}`),
      period,
      object[metric] >= cap ? `Among the busiest 1%: drawn at the height cap (${cap.toLocaleString()}).` : `Height is to scale (capped at ${cap.toLocaleString()}).`,
    ];
    return { text: lines.join("\n"), style };
  };

  const overlay = new deck.MapboxOverlay({ interleaved: false, layers: [], getTooltip: tooltip });
  map.addControl(overlay);

  function render() {
    const value = (d) => scale(d[metric]);
    const flat = heightFactor(map.getZoom()) < 0.2;
    const hexLayer = new deck.H3HexagonLayer({
      id: "history",
      data: hexes,
      getHexagon: (d) => d.hex,
      extruded: !flat, // neighbourhood scale: plain 2D density cells
      coverage: 0.88,
      highPrecision: false, // instanced hexagonal columns at every zoom; exact enough for ~175 m cells this far from the poles
      elevationScale: heightFactor(map.getZoom()),
      getElevation: (d) => value(d) * MAX_HEIGHT_M,
      getFillColor: (d) => [...rampColor(value(d)), 235],
      opacity: flat ? 0.6 : 1, // flat cells let the streets show through
      material: { ambient: 0.55, diffuse: 0.6, shininess: 24, specularColor: [60, 64, 70] },
      pickable: true,
      autoHighlight: true,
      highlightColor: [255, 255, 255, 110],
      updateTriggers: { getElevation: [metric, hexes], getFillColor: [metric, hexes] },
      transitions: motion ? { getElevation: { duration: 650 } } : undefined,
    });
    const ringColor = hexToRgb(TIER_COLORS[0]);
    const ringLayer = new deck.ScatterplotLayer({
      id: "rings",
      data: rings,
      getPosition: (d) => [d.lng, d.lat],
      filled: true,
      stroked: true,
      getFillColor: [255, 255, 255, 40],
      getLineColor: [...ringColor, 255],
      billboard: true, // face the camera, so a tilted map doesn't squash them into slivers
      radiusUnits: "pixels",
      getRadius: 7,
      lineWidthUnits: "pixels",
      getLineWidth: 2.5,
      pickable: true,
      // Drawn on top of the columns: the model's rings must never hide inside observed history.
      parameters: { depthCompare: "always" },
      onClick: ({ object }) => { if (object && onRing) onRing(object.id); },
    });
    overlay.setProps({ layers: [hexLayer, ringLayer] });
  }

  map.on("moveend", () => { if (onMove) onMove(bounds()); });
  let lodFrame = 0;
  map.on("zoom", () => { cancelAnimationFrame(lodFrame); lodFrame = requestAnimationFrame(render); });
  const bounds = () => {
    const b = map.getBounds();
    return { south: b.getSouth(), north: b.getNorth(), west: b.getWest(), east: b.getEast() };
  };
  const onScheme = () => map.setStyle(isDark() ? STYLES.dark : STYLES.light);
  if (darkQuery && darkQuery.addEventListener) darkQuery.addEventListener("change", onScheme);

  await new Promise((resolve) => (map.loaded() ? resolve() : map.once("load", resolve)));
  return {
    map,
    bounds,
    /** `data` is the /api/history/cells response; `label` describes the period for tooltips. */
    setHexes(data, label) {
      period = label;
      hexes = data.cells.map((hex, i) => ({
        hex, borough: data.borough[i] >= 0 ? data.boroughs[data.borough[i]] : "",
        all: data.all[i], injury: data.injury[i], pedestrian: data.pedestrian[i], cyclist: data.cyclist[i],
      }));
      this.setMetric(metric);
    },
    setMetric(key) {
      metric = key;
      ({ cap, scale } = cappedScale(hexes.map((d) => d[metric])));
      render();
    },
    setRings(points) { rings = points; render(); },
    /** The count drawn at full height for the current layer and period. */
    cap: () => cap,
    zoom: () => map.getZoom(),
    resize() { map.resize(); },
    destroy() {
      if (darkQuery && darkQuery.removeEventListener) darkQuery.removeEventListener("change", onScheme);
      map.remove(); // also removes the deck.gl overlay control and frees both WebGL contexts
    },
  };
}
