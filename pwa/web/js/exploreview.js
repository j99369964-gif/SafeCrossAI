// Explore the risk map: an area-level overview when zoomed out, individual intersections when zoomed in.
// The server does the filtering and the capping; this view only draws what it is sent.
import { h } from "./dom.js";
import * as api from "./api.js";
import { mountSharedMap, onMapsAuthFailure, metersForPixels, describeMapsError } from "./gmaps.js";
import { TIER_COLORS, TIER_NAMES, renderIntersectionDetail, loadingBody, errorBody } from "./detail.js";

export const ZOOM_SWITCH = 14;

/** Height of one area-view square, in degrees of latitude, for a map zoom: finer as the user zooms in. */
export function cellForZoom(zoom) {
  if (zoom <= 10) return 0.02;
  if (zoom === 11) return 0.01;
  if (zoom === 12) return 0.005;
  return 0.0025;
}
const FINE_CELL = 0.005;
const DEBOUNCE_MS = 250;

// Filters survive moving between tabs.
const memory = { areas: null, tiers: new Set([0, 1, 2, 3]) };

/** Colour for an average within-area risk percentile (0 to 1): pale yellow -> orange -> red. */
export function riskColor(value) {
  const v = Math.max(0, Math.min(1, value));
  const stops = [[255, 247, 188], [253, 174, 97], [215, 25, 28]];
  const scaled = v * (stops.length - 1);
  const i = Math.min(Math.floor(scaled), stops.length - 2);
  const t = scaled - i;
  const mix = stops[i].map((channel, k) => Math.round(channel + (stops[i + 1][k] - channel) * t));
  return `rgb(${mix[0]},${mix[1]},${mix[2]})`;
}

export function mountExploreView(root, ctx) {
  const { config } = ctx;
  const heading = h("h1", { tabindex: "-1" }, "Explore the risk map");
  const page = h("section", { class: "page" }, heading,
    h("p", { class: "muted" }, "Zoomed out you see how risk varies across areas. Zoom in to see individual intersections and tap one for details."));
  root.append(page);

  if (!config.mapsJsKey) {
    page.append(h("div", { class: "banner banner-warn", role: "alert" }, "The map isn't set up on this server yet (missing the browser Maps JavaScript API key)."));
    return { destroy() {}, heading };
  }

  if (memory.areas === null) memory.areas = new Set(config.areas.map((area) => area.key));
  let destroyed = false;
  let map = null;
  let maps = null;
  let token = 0;
  let debounceTimer = null;
  let gridKey = null;
  let selectedId = null;
  const listeners = [];
  const active = new Map(); // intersection id -> { circle, pixels }
  let unsubscribeAuth = () => {};

  const filterParams = () => ({ areas: [...memory.areas].join(","), tiers: [...memory.tiers].sort().join(",") });
  const filterKey = () => `${filterParams().areas}|${filterParams().tiers}`;

  // ------------------------------------------------------------------ filters
  const areaChips = h("div", { class: "chips", role: "group", "aria-label": "Areas" });
  const tierChips = h("div", { class: "chips", role: "group", "aria-label": "Risk levels" });
  const banner = h("div", { role: "status" });
  const summary = h("p", { class: "muted", role: "status", "aria-live": "polite" }, "Loading...");
  const mapMessage = h("div", {});
  const mapHolder = h("div", {});
  const sheetHost = h("div", {});

  function chip(label, pressed, onToggle) {
    const button = h("button", { type: "button", class: "chip", "aria-pressed": pressed ? "true" : "false" }, label);
    button.addEventListener("click", () => { onToggle(); renderFilters(); refresh(true); });
    return button;
  }
  function renderFilters() {
    areaChips.replaceChildren(...config.areas.map((area) => chip(
      `${area.label}${area.validated ? "" : " (unvalidated)"}`, memory.areas.has(area.key),
      () => (memory.areas.has(area.key) ? memory.areas.delete(area.key) : memory.areas.add(area.key)))));
    tierChips.replaceChildren(...TIER_NAMES.map((name, code) => chip(name, memory.tiers.has(code),
      () => (memory.tiers.has(code) ? memory.tiers.delete(code) : memory.tiers.add(code)))));
    const unvalidated = config.areas.filter((area) => !area.validated && memory.areas.has(area.key));
    banner.replaceChildren(...(unvalidated.length ? [h("div", { class: "banner banner-warn" },
      h("strong", {}, `${unvalidated.map((a) => a.label).join(" and ")}: unvalidated estimate.`),
      " The New York City model was applied to the area's road layout, but there is no crash history there, so the ranking comes from road design alone. Tiers compare intersections within the area with each other, not with New York City, and nothing has checked them against real crashes. Unvalidated intersections are drawn fainter.")] : []));
  }
  renderFilters();

  page.append(
    h("div", { class: "card" }, h("h2", { style: "margin-top:0" }, "Areas"), areaChips, h("h2", {}, "Risk levels"), tierChips),
    banner, summary, mapMessage, mapHolder,
    h("div", { class: "legend" }, TIER_NAMES.map((name, code) => h("span", {}, h("span", { class: "dot", style: `background:${TIER_COLORS[code]}` }), name))),
    sheetHost);

  // ------------------------------------------------------------------ map layers
  const sizeFor = (code) => (code === 0 ? 7 : 6);

  function clearPoints() {
    active.forEach(({ circle }) => circle.setMap(null));
    active.clear();
  }
  function clearGrid() {
    if (!map) return;
    const features = [];
    map.data.forEach((feature) => features.push(feature));
    features.forEach((feature) => map.data.remove(feature));
    gridKey = null;
  }

  async function showGrid(mine) {
    const cell = cellForZoom(map.getZoom());
    const params = { ...filterParams(), cell };
    if (cell <= FINE_CELL) {
      // Small squares are only built for the part of the map in view, so the response stays small.
      const view = map.getBounds();
      if (!view) return;
      const round = (value) => Math.round(value * 400) / 400; // ignore tiny pans
      Object.assign(params, {
        south: round(view.getSouthWest().lat()), west: round(view.getSouthWest().lng()),
        north: round(view.getNorthEast().lat()), east: round(view.getNorthEast().lng()),
      });
    }
    const key = JSON.stringify(params);
    if (gridKey === key) { summary.textContent = "Area view: zoom in to see individual intersections."; return; }
    const geojson = await api.exploreGrid(params);
    if (mine !== token || destroyed) return;
    clearGrid();
    map.data.addGeoJson(geojson);
    map.data.setStyle((feature) => ({
      fillColor: riskColor(feature.getProperty("mean_probability")), fillOpacity: 0.6, strokeColor: "#555555", strokeWeight: 0.4, clickable: true,
    }));
    gridKey = key;
    const cells = geojson.features.length;
    summary.textContent = cells ? "Area view: darker squares are areas with higher average relative risk. Zoom in for finer squares, then for individual intersections." : "Nothing matches these filters.";
  }

  function styleFor(point, id) {
    const unvalidated = point.unvalidated === 1;
    const isSelected = id === selectedId;
    return {
      fillColor: TIER_COLORS[point.tier], fillOpacity: unvalidated ? 0.35 : 0.9,
      strokeColor: isSelected ? "#000000" : unvalidated ? TIER_COLORS[point.tier] : "#ffffff",
      strokeOpacity: unvalidated ? 0.7 : 1, strokeWeight: isSelected ? 3 : 1,
    };
  }

  async function showPoints(mine) {
    const bounds = map.getBounds();
    if (!bounds) return;
    const south = bounds.getSouthWest().lat(), west = bounds.getSouthWest().lng();
    const north = bounds.getNorthEast().lat(), east = bounds.getNorthEast().lng();
    const result = await api.explorePoints({ south, north, west, east, ...filterParams() });
    if (mine !== token || destroyed) return;
    const wanted = new Set(result.id);
    for (const [id, entry] of active) {
      if (!wanted.has(id)) { entry.circle.setMap(null); active.delete(id); }
    }
    result.id.forEach((id, i) => {
      if (active.has(id)) return;
      const point = { tier: result.tier[i], unvalidated: result.unvalidated[i] };
      const position = { lat: result.lat[i], lng: result.lng[i] };
      const pixels = sizeFor(point.tier);
      const circle = new maps.Circle({ center: position, radius: metersForPixels(map, pixels), zIndex: 10 - point.tier, map, ...styleFor(point, id) });
      circle.addListener("click", () => openSheet(id, point));
      active.set(id, { circle, pixels, point });
    });
    summary.textContent = result.capped
      ? `${result.total.toLocaleString()} intersections in view; showing the ${result.shown.toLocaleString()} highest-risk. Zoom in further to see the rest.`
      : `${result.total.toLocaleString()} intersection${result.total === 1 ? "" : "s"} in view.`;
  }

  async function refresh(immediate) {
    if (!map) return;
    clearTimeout(debounceTimer);
    const run = async () => {
      const mine = ++token;
      if (memory.areas.size === 0 || memory.tiers.size === 0) {
        clearPoints(); clearGrid();
        summary.textContent = "Choose at least one area and one risk level.";
        return;
      }
      try {
        if (map.getZoom() < ZOOM_SWITCH) { clearPoints(); await showGrid(mine); }
        else { clearGrid(); await showPoints(mine); }
      } catch (problem) {
        if (mine === token && !destroyed) summary.textContent = problem.message;
      }
    };
    if (immediate) await run(); else debounceTimer = setTimeout(run, DEBOUNCE_MS);
  }

  // ------------------------------------------------------------------ details sheet
  function closeSheet() {
    selectedId = null;
    sheetHost.replaceChildren();
    active.forEach(({ circle, point }, id) => circle.setOptions(styleFor(point, id)));
  }
  async function openSheet(id, point) {
    selectedId = id;
    active.forEach((entry, key) => entry.circle.setOptions(styleFor(entry.point, key)));
    sheetHost.replaceChildren(h("div", { class: "sheet", role: "dialog", "aria-label": "Intersection details" }, loadingBody()));
    try {
      const detail = await api.getIntersection(id);
      if (destroyed || selectedId !== id) return;
      const sheet = h("div", { class: "sheet", role: "dialog", "aria-label": "Intersection details" }, renderIntersectionDetail(detail, { onClose: closeSheet }));
      sheetHost.replaceChildren(sheet);
      const closeButton = sheet.querySelector(".sheet-close");
      if (closeButton) closeButton.focus();
    } catch (problem) {
      if (!destroyed) sheetHost.replaceChildren(h("div", { class: "sheet", role: "alert" }, errorBody(problem.message, closeSheet)));
    }
  }

  // ------------------------------------------------------------------ start
  unsubscribeAuth = onMapsAuthFailure((message) => mapMessage.replaceChildren(h("div", { class: "banner banner-error", role: "alert" }, message)));
  mountSharedMap(config.mapsJsKey, mapHolder).then(({ maps: mapsApi, map: mapInstance }) => {
    if (destroyed) return;
    maps = mapsApi; map = mapInstance;
    const info = new maps.InfoWindow();
    listeners.push(map.addListener("idle", () => refresh(false)));
    listeners.push(map.addListener("zoom_changed", () => {
      const resize = (entry) => entry.circle.setRadius(metersForPixels(map, entry.pixels));
      active.forEach(resize);
      refresh(false);
    }));
    listeners.push(map.data.addListener("click", (event) => {
      info.setContent(h("div", { style: "font-size:13px;color:#1b1f24" },
        h("div", { style: "font-weight:bold" }, "Area average"),
        h("div", {}, `Average relative risk percentile: ${Math.round(event.feature.getProperty("mean_probability") * 100)}`),
        h("div", {}, `${event.feature.getProperty("point_count")} intersections`)));
      info.setPosition(event.latLng);
      info.open(map);
    }));
    const b = config.bounds;
    map.fitBounds({ south: b.south, north: b.north, west: b.west, east: b.east }, 30);
    refresh(true);
  }).catch((problem) => {
    if (!destroyed) mapMessage.replaceChildren(h("div", { class: "banner banner-error", role: "alert" }, describeMapsError(problem)));
  });

  return {
    heading,
    destroy() {
      destroyed = true;
      clearTimeout(debounceTimer);
      unsubscribeAuth();
      listeners.forEach((listener) => listener.remove());
      clearPoints();
      clearGrid();
    },
  };
}
