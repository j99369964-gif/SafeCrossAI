// Explore the risk map: an area-level overview when zoomed out, individual intersections when zoomed in.
// The server does the filtering and the capping; this view only draws what it is sent.
// A second, optional view shows OBSERVED crash history in 3D (see history3d.js): city scale -> 3D hexagon columns,
// neighbourhood -> 2D risk squares, intersection -> SafeCross dots. Observed history and the model's ranking are kept
// visually separate: columns are what happened, red rings are where the model says to pay attention.
import { h, pageHeader } from "./dom.js";
import * as api from "./api.js";
import { mountSharedMap, onMapsAuthFailure, describeMapsError } from "./gmaps.js";
import { createCanvasLayer } from "./canvaslayer.js";
import { METRICS, RAMP_CSS, mountHistoryMap } from "./history3d.js";
import { TIER_COLORS, TIER_NAMES, renderIntersectionDetail, loadingBody, errorBody, showSheet, hideSheet } from "./detail.js";

export const ZOOM_SWITCH = 14;

/** Height of one area-view square, in degrees of latitude, for a map zoom: finer as the user zooms in. */
export function cellForZoom(zoom) {
  if (zoom <= 10) return 0.02;
  if (zoom === 11) return 0.01;
  if (zoom === 12) return 0.005;
  return 0.0025;
}
const FINE_CELL = 0.005;
// 3D view: SafeCross rings only appear at neighbourhood zoom; at city scale they would overplot just like crash dots.
const RING_ZOOM = 13.5;
const DEBOUNCE_MS = 250;

// Filters survive moving between tabs.
const memory = { areas: null, tiers: new Set([0, 1, 2, 3]), view: "risk", metric: "all", period: null, rings: true };

const monthName = (ym) => new Date(`${ym}-01T12:00:00`).toLocaleDateString(undefined, { month: "short", year: "numeric" });
export const periodLabel = (from, to) => `${monthName(from)} – ${monthName(to)}`;

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
  const { header, heading } = pageHeader("Risk map · weekly snapshot", "Explore the risk map",
    "Zoomed out you see how risk varies across areas. Zoom in to see individual intersections and tap one for details. Switch to 3D crash history to see where crashes have happened over the years.");
  const page = h("section", { class: "page" }, header);
  root.append(page);

  if (!config.mapsJsKey && !config.history) {
    page.append(h("div", { class: "banner banner-warn", role: "alert" }, "The map isn't set up on this server yet (missing the browser Maps JavaScript API key)."));
    return { destroy() {}, heading };
  }

  if (memory.areas === null) memory.areas = new Set(config.areas.map((area) => area.key));
  let destroyed = false;
  let map = null;
  let layer = null; // dots and area squares, drawn on one canvas (see canvaslayer.js)
  let token = 0;
  let debounceTimer = null;
  let gridKey = null;
  let selectedId = null;
  const listeners = [];
  let points = []; // intersections in view: { id, lat, lng, tier, unvalidated }
  let unsubscribeAuth = () => {};

  const filterParams = () => ({ areas: [...memory.areas].join(","), tiers: [...memory.tiers].sort().join(",") });
  const filterKey = () => `${filterParams().areas}|${filterParams().tiers}`;

  // ------------------------------------------------------------------ filters
  const areaChips = h("div", { class: "chips", role: "group", "aria-label": "Areas" });
  const tierChips = h("div", { class: "chips", role: "group", "aria-label": "Risk levels" });
  const banner = h("div", { role: "status" });
  const summary = h("p", { class: "muted", role: "status", "aria-live": "polite" }, "Loading...");
  const mapMessage = h("div", {});
  const mapHolder = h("div", {}, h("div", { class: "map map-loading", "aria-hidden": "true" }, "Loading map"));
  const sheetHost = h("div", { class: "sheet-host" });

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
      " The New York City model was applied to the area's road layout, but there is no crash history there, so the ranking comes from road design alone. Tiers compare each intersection with nearby intersections in the same area, not with New York City, and nothing has checked them against real crashes. Unvalidated intersections are drawn fainter.")] : []));
  }
  renderFilters();

  const riskSection = h("div", { class: "explore-mode" },
    h("div", { class: "card filter-card" }, h("h2", {}, "Areas"), areaChips, h("h2", {}, "Risk levels"), tierChips),
    banner, summary, mapMessage, mapHolder,
    h("div", { class: "legend" }, TIER_NAMES.map((name, code) => h("span", {}, h("span", { class: "dot", style: `background:${TIER_COLORS[code]}` }), name))));
  const historySection = h("div", { class: "explore-mode" });

  // ------------------------------------------------------------------ view toggle
  const viewOption = (value, label) => h("label", {},
    h("input", { type: "radio", name: "explore-view", value, checked: memory.view === value, onchange: () => setView(value) }),
    h("span", {}, label));
  const viewToggle = config.history
    ? h("div", { class: "segmented segmented-2 view-toggle", role: "radiogroup", "aria-label": "Map view" },
      viewOption("risk", "SafeCross risk"), viewOption("history", "3D crash history"))
    : null;
  page.append(viewToggle, riskSection, historySection, sheetHost);

  // ------------------------------------------------------------------ map layers
  const sizeFor = (code) => (code === 0 ? 7 : 6);

  function clearPoints() {
    points = [];
    if (layer) layer.setDots([]);
  }
  function clearGrid() {
    if (layer) layer.setRects([]);
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
    // Every cell is an axis-aligned square, so its first and third corners are enough.
    layer.setRects(geojson.features.map(({ geometry, properties }) => {
      const [[west, south], , [east, north]] = geometry.coordinates[0];
      return {
        south, west, north, east, fill: riskColor(properties.mean_probability), alpha: 0.6,
        stroke: "rgba(85,85,85,.7)", strokeWidth: 0.4, data: properties,
      };
    }));
    gridKey = key;
    const cells = geojson.features.length;
    summary.textContent = cells ? "Area view: darker squares are areas with higher average risk across the whole region. Zoom in for individual intersections, which are ranked against their own neighbourhood." : "Nothing matches these filters.";
  }

  function drawPoints() {
    if (!layer) return;
    layer.setDots(points.map((point) => {
      const unvalidated = point.unvalidated === 1;
      const isSelected = point.id === selectedId;
      return {
        lat: point.lat, lng: point.lng, r: sizeFor(point.tier), z: isSelected ? 50 : 10 - point.tier,
        fill: TIER_COLORS[point.tier], alpha: unvalidated ? 0.35 : 0.9,
        stroke: isSelected ? "#000000" : unvalidated ? TIER_COLORS[point.tier] : "#ffffff",
        strokeAlpha: unvalidated ? 0.7 : 1, strokeWidth: isSelected ? 3 : 1, data: point,
      };
    }));
  }

  async function showPoints(mine) {
    const bounds = map.getBounds();
    if (!bounds) return;
    const south = bounds.getSouthWest().lat(), west = bounds.getSouthWest().lng();
    const north = bounds.getNorthEast().lat(), east = bounds.getNorthEast().lng();
    const result = await api.explorePoints({ south, north, west, east, ...filterParams() });
    if (mine !== token || destroyed) return;
    points = result.id.map((id, i) => ({
      id, lat: result.lat[i], lng: result.lng[i], tier: result.tier[i], unvalidated: result.unvalidated[i],
    }));
    drawPoints();
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
    hideSheet(sheetHost);
    drawPoints();
  }
  async function openSheet(id) {
    selectedId = id;
    drawPoints();
    showSheet(sheetHost, loadingBody());
    try {
      const detail = await api.getIntersection(id);
      if (destroyed || selectedId !== id) return;
      const sheet = showSheet(sheetHost, renderIntersectionDetail(detail, { onClose: closeSheet }));
      const closeButton = sheet.querySelector(".sheet-close");
      if (closeButton) closeButton.focus();
    } catch (problem) {
      if (!destroyed) showSheet(sheetHost, errorBody(problem.message, closeSheet), { role: "alert" });
    }
  }

  // ------------------------------------------------------------------ start (the risk map loads the first time it is shown)
  let riskStarted = false;
  function startRiskMap() {
  if (riskStarted) return;
  riskStarted = true;
  if (!config.mapsJsKey) {
    mapHolder.replaceChildren(h("div", { class: "banner banner-warn", role: "alert" }, "The risk map isn't set up on this server yet (missing the browser Maps JavaScript API key)."));
    return;
  }
  unsubscribeAuth = onMapsAuthFailure((message) => mapMessage.replaceChildren(h("div", { class: "banner banner-error", role: "alert" }, message)));
  mountSharedMap(config.mapsJsKey, mapHolder).then(({ maps, map: mapInstance }) => {
    if (destroyed) return;
    map = mapInstance;
    const info = new maps.InfoWindow();
    layer = createCanvasLayer(maps, map, {
      onClick(hit, event) {
        if (hit.kind === "dot") { info.close(); openSheet(hit.data.id); return; }
        info.setContent(h("div", { style: "font-size:13px;color:#1b1f24" },
          h("div", { style: "font-weight:bold" }, "Area average"),
          h("div", {}, `Average relative risk percentile: ${Math.round(hit.data.mean_probability * 100)}`),
          h("div", {}, `${hit.data.point_count} intersections`)));
        info.setPosition(event.latLng);
        info.open(map);
      },
    });
    listeners.push(map.addListener("idle", () => refresh(false)));
    const b = config.bounds;
    map.fitBounds({ south: b.south, north: b.north, west: b.west, east: b.east }, 30);
    refresh(true);
  }).catch((problem) => {
    if (!destroyed) mapMessage.replaceChildren(h("div", { class: "banner banner-error", role: "alert" }, describeMapsError(problem)));
  });
  }

  // ------------------------------------------------------------------ 3D crash history
  const history = config.history;
  let history3d = null;
  let historyStarted = false;
  let historyToken = 0;
  let ringToken = 0;
  let ringTimer = null;
  let historyData = null;
  if (history && !memory.period) memory.period = { ...history.presets[0] };

  const metricChips = h("div", { class: "chips", role: "radiogroup", "aria-label": "Historical layer" });
  const periodChips = h("div", { class: "chips", role: "radiogroup", "aria-label": "Historical period" });
  const customFields = h("div", { class: "month-range" });
  const ringChip = h("div", { class: "chips" });
  const ringHint = h("p", { class: "muted small ring-hint" });
  const historyStatus = h("p", { class: "muted", role: "status", "aria-live": "polite" }, "");
  const historyMessage = h("div", {});
  const historyHolder = h("div", {});
  const topList = h("ol", { class: "top-cells" });
  const scaleNote = h("p", { class: "muted small" });

  function radioChip(label, checked, onPick, title) {
    return h("button", { type: "button", class: "chip", role: "radio", "aria-checked": checked ? "true" : "false", "aria-pressed": checked ? "true" : "false", title, onclick: onPick }, label);
  }
  const ringSwatch = () => h("span", { class: "ring-swatch", style: `border-color:${TIER_COLORS[0]}` });

  function renderHistoryControls() {
    metricChips.replaceChildren(...METRICS.map((m) => radioChip(m.label, memory.metric === m.key, () => {
      memory.metric = m.key;
      renderHistoryControls();
      if (history3d) history3d.setMetric(m.key);
      describeHistory();
    }, m.hint ? `Crashes in which ${m.hint}` : undefined)));
    const custom = memory.period.key === "custom";
    periodChips.replaceChildren(
      ...history.presets.map((preset) => radioChip(preset.label, memory.period.key === preset.key, () => {
        memory.period = { ...preset };
        renderHistoryControls();
        loadHistory();
      })),
      radioChip("Custom", custom, () => { memory.period = { ...memory.period, key: "custom" }; renderHistoryControls(); }));
    const monthInput = (label, field) => h("label", {}, label, h("input", {
      type: "month", min: history.first, max: history.last, value: memory.period[field], required: true,
      onchange: (event) => { if (event.target.value) { memory.period[field] = event.target.value; loadHistory(); } },
    }));
    customFields.replaceChildren(...(custom ? [monthInput("From", "from"), monthInput("To", "to")] : []));
    ringChip.replaceChildren(h("button", {
      type: "button", class: "chip", "aria-pressed": memory.rings ? "true" : "false",
      onclick: () => { memory.rings = !memory.rings; renderHistoryControls(); loadRings(); },
    }, ringSwatch(), "SafeCross highest-priority rings"));
  }

  if (history) {
    renderHistoryControls();
    historySection.append(
      h("div", { class: "card filter-card" },
        h("h2", {}, "Historical layer"), metricChips,
        h("h2", {}, "Historical period"), periodChips, customFields,
        h("h2", {}, "Model overlay"), ringChip, ringHint),
      h("div", { class: "banner banner-info" },
        h("strong", {}, "Observed history, not predictions."),
        " Each column is one hexagon of about 0.1 km². Its height and colour show how many crashes were recorded there in the chosen period. "
        + "The red rings are separate: they are SafeCross's current highest-priority intersections. Crash history covers New York City only."),
      historyStatus, historyMessage, historyHolder,
      h("div", { class: "legend" },
        h("span", { class: "ramp-legend" }, "Fewer", h("span", { class: "ramp", style: `background:${RAMP_CSS}` }), "More crashes"),
        h("span", {}, ringSwatch(), "SafeCross highest-priority (top 10% nearby)")),
      scaleNote,
      h("div", { class: "card" }, h("h2", {}, "Highest concentrations in this period"), topList));
  }

  function describeHistory() {
    if (!historyData) return;
    const metric = METRICS.find((m) => m.key === memory.metric);
    const values = historyData[memory.metric];
    historyStatus.textContent = `${metric.label}, ${periodLabel(historyData.from, historyData.to)}: ${historyData.totals[memory.metric].toLocaleString()} across ${historyData.cells.length.toLocaleString()} hexagons. Taller, brighter columns had more.`;
    const cap = history3d ? history3d.cap() : 0;
    scaleNote.textContent = `Column height is proportional to the count up to ${cap.toLocaleString()} (the 99th percentile for this layer and period). `
      + "The busiest 1% of hexagons are drawn at that height so a few extreme spots don't tower over everything else; tooltips and the list below show real counts. "
      + "Drag to pan; right-drag, Ctrl-drag or a two-finger drag rotates and tilts.";
    const order = values.map((_, i) => i).sort((a, b) => values[b] - values[a]).slice(0, 5);
    topList.replaceChildren(...order.map((i) => {
      const borough = historyData.borough[i] >= 0 ? historyData.boroughs[historyData.borough[i]] : "New York City";
      return h("li", {}, h("strong", {}, `${values[i].toLocaleString()} ${metric.noun.toLowerCase()}`),
        ` · ${borough}`, memory.metric === "all" ? "" : ` · ${historyData.all[i].toLocaleString()} crashes in all`);
    }));
  }

  async function loadHistory() {
    if (!history3d) return;
    const mine = ++historyToken;
    const { from, to } = memory.period;
    historyStatus.textContent = `Adding up ${periodLabel(from, to)}...`;
    try {
      const data = await api.historyCells({ from, to });
      if (mine !== historyToken || destroyed) return;
      historyData = data;
      history3d.setHexes(data, periodLabel(data.from, data.to));
      describeHistory();
    } catch (problem) {
      if (mine === historyToken && !destroyed) historyStatus.textContent = problem.message;
    }
  }

  function loadRings() {
    if (!history3d) return;
    clearTimeout(ringTimer);
    const zoomedOut = history3d.zoom() < RING_ZOOM;
    ringHint.textContent = memory.rings && zoomedOut ? "Zoom in to a neighbourhood to see the rings." : "";
    if (!memory.rings || zoomedOut) { ringToken++; history3d.setRings([]); return; }
    ringTimer = setTimeout(async () => {
      const mine = ++ringToken;
      try {
        const result = await api.explorePoints({ ...history3d.bounds(), areas: "nyc", tiers: "0" });
        if (mine !== ringToken || destroyed || !memory.rings) return;
        history3d.setRings(result.id.map((id, i) => ({ id, lat: result.lat[i], lng: result.lng[i] })));
      } catch { /* the rings are an extra; the history layer works without them */ }
    }, DEBOUNCE_MS);
  }

  function startHistoryMap() {
    if (historyStarted) { if (history3d) history3d.resize(); return; }
    historyStarted = true;
    historyMessage.replaceChildren();
    // MapLibre measures its container, so the element is in the page (showing the loading shimmer) while it starts.
    const element = h("div", { class: "map map-3d map-loading", role: "region", "aria-label": "3D crash history map" });
    historyHolder.replaceChildren(element);
    mountHistoryMap(element, { onRing: (id) => openSheet(id), onMove: loadRings }).then((instance) => {
      if (destroyed) { instance.destroy(); return; }
      history3d = instance;
      element.classList.remove("map-loading");
      history3d.resize();
      loadHistory();
      loadRings();
    }).catch((problem) => {
      historyStarted = false;
      if (destroyed) return;
      historyHolder.replaceChildren();
      historyMessage.replaceChildren(h("div", { class: "banner banner-error", role: "alert" }, problem.message));
    });
  }

  function setView(view) {
    memory.view = view;
    riskSection.hidden = view !== "risk";
    historySection.hidden = view !== "history";
    if (view === "history") startHistoryMap(); else startRiskMap();
  }
  setView(history ? memory.view : "risk");

  return {
    heading,
    destroy() {
      destroyed = true;
      clearTimeout(debounceTimer);
      unsubscribeAuth();
      listeners.forEach((listener) => listener.remove());
      if (layer) layer.destroy();
      clearTimeout(ringTimer);
      if (history3d) history3d.destroy();
    },
  };
}
