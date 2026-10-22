// The main screen: plan a trip, compare the route options, see them on the map.
import { h, boldParts, icon, pageHeader, countUp } from "./dom.js";
import * as api from "./api.js";
import { mountSharedMap, onMapsAuthFailure, describeMapsError } from "./gmaps.js";
import { createTripMap } from "./routemap.js";
import { avoidIds, getReport } from "./reports.js";
import { TIER_COLORS, TIER_NAMES, TIER_SHORT, splitStreets, tierPill, renderIntersectionDetail, renderIntersectionSummary, summaryMessage, loadingBody, errorBody, showSheet, hideSheet } from "./detail.js";

export const EXAMPLE_TRIP = { from: "Columbus Circle, New York, NY", to: "Barclays Center, Brooklyn, NY", mode: "Driving" };
const MODES = ["Driving", "Cycling", "Walking"];
const MODE_ICONS = { Driving: "car", Cycling: "bike", Walking: "walk" };

// Kept in memory only, for as long as the page stays open. Route results are Google Maps Platform content, so they are
// never written to localStorage, IndexedDB or the service-worker cache.
const memory = { form: { from: "", to: "", mode: "Driving" }, trip: null, selected: null, tiers: new Set([0, 1]), sort: "route", node: null };

export function resetRouteMemory() {
  memory.form = { from: "", to: "", mode: "Driving" };
  memory.trip = null;
  memory.selected = null;
  memory.tiers = new Set([0, 1]);
  memory.sort = "route";
  memory.node = null;
}

function setupNotice(config) {
  const missing = [];
  if (!config.routesConfigured) missing.push("the server-side Routes API key");
  if (!config.mapsJsKey) missing.push("the browser Maps JavaScript API key");
  return h("div", { class: "banner banner-warn", role: "alert" },
    h("strong", {}, "Route planning isn't set up on this server yet."),
    ` Missing: ${missing.join(" and ")}. The site owner needs to add it (see pwa/README_PWA.md).`);
}

export function mountRouteView(root, ctx) {
  const { config } = ctx;
  const { header, heading } = pageHeader("New York City · Westchester", "Plan a safer route",
    "Compare route options by travel time and by a risk score that adds up every intersection each one passes.");
  const page = h("section", { class: "page" }, header);
  root.append(page);

  if (!config.routesConfigured || !config.mapsJsKey) {
    page.append(setupNotice(config));
    return { destroy() {}, heading };
  }

  let destroyed = false;
  let tripMap = null;
  let unsubscribeAuth = () => {};
  let busy = false;

  // ------------------------------------------------------------------ form
  const fromInput = h("input", { type: "text", id: "from", name: "from", autocomplete: "off", enterkeyhint: "next", placeholder: "e.g. Columbus Circle, or 40.7681, -73.9819" });
  const toInput = h("input", { type: "text", id: "to", name: "to", autocomplete: "off", enterkeyhint: "go", placeholder: "e.g. Barclays Center, Brooklyn" });
  fromInput.value = memory.form.from;
  toInput.value = memory.form.to;

  const modeRadios = MODES.map((mode) => {
    const radio = h("input", { type: "radio", name: "mode", value: mode });
    radio.checked = mode === memory.form.mode;
    return radio;
  });
  const modeGroup = h("fieldset", {}, h("legend", {}, "Travel mode"),
    h("div", { class: "segmented", role: "radiogroup", "aria-label": "Travel mode" },
      modeRadios.map((radio) => h("label", {}, radio, h("span", {}, icon(MODE_ICONS[radio.value], 18), radio.value)))));

  const submitButton = h("button", { type: "submit", class: "btn" }, "Find routes");
  const exampleButton = h("button", { type: "button", class: "btn btn-ghost", onclick: () => runExample() }, "Try an example trip");
  const locationButton = h("button", { type: "button", class: "input-action", onclick: () => useMyLocation(), "aria-label": "Use my location as the starting point", title: "Use my location" }, icon("locate"));

  const status = h("div", { role: "status", "aria-live": "polite", class: "muted status-line" });
  const errorBox = h("div", { role: "alert" });
  const resultsEl = h("div", { id: "results", class: "results" });
  const avoiding = avoidIds().length;
  const avoidNote = avoiding
    ? h("p", { class: "form-hint avoid-hint" }, icon("flag", 16),
      `Steering around ${avoiding} intersection${avoiding === 1 ? "" : "s"} you reported. `, h("a", { href: "#/report" }, "Manage reports"))
    : h("p", { class: "form-hint avoid-hint" }, "Know an intersection that feels dangerous? ", h("a", { href: "#/report" }, "Report it"), " and routes will steer around it.");

  // A start ring and a destination diamond joined by a dashed line (see .trip-form in styles.css).
  const form = h("form", { class: "card trip-form", novalidate: true, onsubmit: (event) => { event.preventDefault(); search(); } },
    h("div", { class: "trip-fields" },
      h("div", { class: "trip-row" }, h("span", { class: "trip-pin trip-pin-start", "aria-hidden": "true" }),
        h("div", { class: "field" }, h("label", { for: "from" }, "From"), fromInput, locationButton)),
      h("div", { class: "trip-row" }, h("span", { class: "trip-pin trip-pin-end", "aria-hidden": "true" }),
        h("div", { class: "field" }, h("label", { for: "to" }, "To"), toInput))),
    modeGroup,
    h("div", { class: "btn-row" }, submitButton, exampleButton),
    h("p", { class: "form-hint" },
      "Places are assumed to be in New York (the city or Westchester County) unless you include another place name."),
    avoidNote);
  page.append(form, status, errorBox, resultsEl);

  const currentMode = () => (modeRadios.find((radio) => radio.checked) || modeRadios[0]).value;
  const showError = (message) => errorBox.replaceChildren(message ? h("div", { class: "banner banner-error" }, message) : "");

  function useMyLocation() {
    if (!("geolocation" in navigator)) { showError("This browser can't share your location. Type a starting point instead."); return; }
    showError("");
    status.textContent = "Finding your location...";
    locationButton.classList.add("is-locating");
    navigator.geolocation.getCurrentPosition(
      (position) => {
        locationButton.classList.remove("is-locating");
        fromInput.value = `${position.coords.latitude.toFixed(5)}, ${position.coords.longitude.toFixed(5)}`;
        status.textContent = "Using your current location as the starting point.";
      },
      (problem) => {
        locationButton.classList.remove("is-locating");
        status.textContent = "";
        showError(problem && problem.code === 1
          ? "Location permission was denied. Allow it in your browser settings, or type a starting point."
          : "Couldn't get your location. Type a starting point instead.");
      },
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 60000 },
    );
  }

  function runExample() {
    fromInput.value = EXAMPLE_TRIP.from;
    toInput.value = EXAMPLE_TRIP.to;
    modeRadios.forEach((radio) => { radio.checked = radio.value === EXAMPLE_TRIP.mode; });
    return search();
  }

  async function search() {
    if (busy) return;
    const origin = fromInput.value.trim();
    const destination = toInput.value.trim();
    memory.form = { from: origin, to: destination, mode: currentMode() };
    showError("");
    if (!origin || !destination) { showError("Enter both a starting point and a destination."); return; }
    busy = true;
    submitButton.disabled = true;
    form.classList.add("is-busy");
    status.replaceChildren(h("span", { class: "spinner", "aria-hidden": "true" }), "Finding route options...");
    if (tripMap) { tripMap.destroy(); tripMap = null; }
    hideSheet(sheetHost);
    resultsEl.replaceChildren(resultsSkeleton());
    try {
      const trip = await api.findRoutes({ origin, destination, mode: memory.form.mode, avoid: avoidIds() });
      if (destroyed) return;
      memory.trip = trip;
      memory.selected = trip.recommended;
      memory.node = null;
      status.textContent = "";
      renderResults(true);
    } catch (problem) {
      if (destroyed) return;
      status.textContent = "";
      memory.trip = null;
      resultsEl.replaceChildren();
      showError(problem.message || "Something went wrong. Please try again.");
    } finally {
      busy = false;
      submitButton.disabled = false;
      form.classList.remove("is-busy");
    }
  }

  function resultsSkeleton() {
    return h("div", { "aria-hidden": "true" },
      h("div", { class: "skeleton skeleton-title", style: "width:40%;margin-top:28px" }),
      h("div", { class: "skeleton skeleton-line", style: "width:70%" }),
      h("div", { class: "cards" }, [0, 1, 2].map(() => h("div", { class: "card skeleton-card" },
        h("div", { class: "skeleton skeleton-title" }),
        h("div", { class: "skeleton skeleton-num" }),
        h("div", { class: "skeleton skeleton-line" }),
        h("div", { class: "skeleton skeleton-line", style: "width:60%" })))));
  }

  // ------------------------------------------------------------------ results
  const cardsEl = h("div", { class: "cards" });
  const filtersEl = h("div", {});
  const topEl = h("div", {});
  const listEl = h("div", {});
  const sheetHost = h("div", { class: "sheet-host" });
  let resultsHeading = null;
  let detailToken = 0;

  const selectedRoute = () => memory.trip.routes[memory.selected];

  // One button that always names the selected route, so it's clear which option will open on the phone.
  const mapsButton = h("a", { class: "btn btn-block maps-open", target: "_blank", rel: "noopener noreferrer" });
  const mapsHint = h("p", { class: "muted small maps-hint" });
  const mapsBar = h("div", { class: "maps-bar" }, mapsButton, mapsHint);
  const PASS_VERB = { DRIVE: "drive", BICYCLE: "ride", WALK: "walk" };

  function renderMapsLink() {
    const route = selectedRoute();
    const url = route.googleMapsUrl || memory.trip.googleMapsUrl;
    mapsButton.href = url;
    mapsButton.style.setProperty("--route-color", route.color);
    mapsButton.setAttribute("aria-label", `Open ${route.label} in Google Maps (opens the Google Maps app or a new tab)`);
    mapsButton.replaceChildren(h("span", { class: "route-swatch", "aria-hidden": "true" }), `Open ${route.label} in Google Maps`, icon("external", 18));
    const pinned = /[?&]waypoints=/.test(url);
    mapsHint.textContent = pinned
      ? `Opens ${route.label} as it's drawn on the map. To keep Google on this route, the link adds a few stops along the way; just ${PASS_VERB[memory.trip.mode] || "go"} through them. Tap another card to switch routes.`
      : `Opens ${route.label} in Google Maps. Google may suggest a slightly different way on short trips.`;
  }

  function select(index) {
    if (index === memory.selected) return;
    memory.selected = index;
    updateCardSelection();
    renderMapsLink();
    renderFilters();
    renderTop();
    renderList(true);
    if (tripMap) tripMap.highlight(index);
  }

  function setTiers(tiers) {
    memory.tiers = tiers;
    renderFilters();
    renderList(true);
    if (tripMap) tripMap.setTiers(tiers);
  }

  // Cards are built once per result and then updated in place, so changing the selection animates instead of redrawing.
  function renderCards() {
    const trip = memory.trip;
    const maxScore = Math.max(...trip.routes.map((route) => route.score), 0.0001);
    cardsEl.replaceChildren(...trip.routes.map((route, index) => {
      const timeDelta = route.deltaMinutes === null ? null : h("div", { class: "delta" }, `${route.deltaMinutes >= 0 ? "+" : ""}${route.deltaMinutes} min`);
      const scoreDelta = route.scoreChangePct === null ? null
        : h("div", { class: `delta${route.scoreChangePct < 0 ? " good" : ""}` }, `${route.scoreChangePct > 0 ? "+" : ""}${route.scoreChangePct}%`);
      const caption = [route.distanceText, `${route.nIntersections} intersections`, route.nHot ? `${route.nHot} hot spot${route.nHot === 1 ? "" : "s"}` : "no hot spots", `${route.nHigh} high-risk`];
      if (route.nUnvalidated) caption.push(`${route.nUnvalidated} in an unvalidated area`);
      const reportedBadge = route.reported
        ? h("span", { class: "badge badge-warn" }, `Passes ${route.reported} you reported`) : null;
      const scoreValue = h("div", { class: "metric-value" });
      countUp(scoreValue, route.score, 1, 800 + index * 120);
      // The whole card is clickable; the button inside is the keyboard and screen-reader route to the same action.
      return h("article", { class: "card route-card", "aria-label": route.label, style: `--i:${index};--route-color:${route.color}`, onclick: () => select(index) },
        h("h3", {}, route.label),
        h("div", { class: "badges" }, route.badges.map((badge) => h("span", { class: "badge" }, badge)), reportedBadge),
        h("div", { class: "metrics" },
          h("div", {}, h("div", { class: "metric-label" }, "Travel time"), h("div", { class: "metric-value" }, route.durationText), timeDelta),
          h("div", {}, h("div", { class: "metric-label" }, "Risk score"), scoreValue, scoreDelta)),
        h("div", { class: "score-bar", role: "img", "aria-label": `Risk score ${route.score.toFixed(1)}, ${Math.round((route.score / maxScore) * 100)}% of the highest option` },
          h("span", { style: `width:${Math.max(3, (route.score / maxScore) * 100)}%;background:${route.color}` })),
        h("p", { class: "muted small", style: "margin:8px 0 12px" }, caption.join(" · ")),
        h("button", { type: "button", class: "btn btn-small btn-ghost card-select" }));
    }));
    updateCardSelection();
  }

  function updateCardSelection() {
    [...cardsEl.children].forEach((card, index) => {
      const selected = index === memory.selected;
      card.classList.toggle("is-selected", selected);
      const button = card.querySelector(".card-select");
      button.classList.toggle("btn-ghost", !selected);
      button.setAttribute("aria-pressed", selected ? "true" : "false");
      button.textContent = selected ? "Showing details" : "Show details";
    });
  }

  function renderFilters() {
    const route = selectedRoute();
    const counts = [0, 0, 0, 0];
    route.stops.forEach((stop) => { counts[stop.tier] += 1; });
    const chips = TIER_NAMES.map((name, code) => {
      const on = memory.tiers.has(code);
      const button = h("button", { type: "button", class: "chip", "aria-pressed": on ? "true" : "false" },
        h("span", { class: "dot", style: `background:${TIER_COLORS[code]}`, "aria-hidden": "true" }), `${TIER_SHORT[code]} (${counts[code]})`);
      button.addEventListener("click", () => {
        const next = new Set(memory.tiers);
        if (on) next.delete(code); else next.add(code);
        setTiers(next);
      });
      return button;
    });
    filtersEl.replaceChildren(
      h("h2", {}, "Intersections along the way"),
      h("p", { class: "muted small", style: "margin-top:0" }, `${route.label}: choose which risk levels to show on the map and in the list. Tap a dot or a row for details.`),
      h("div", { class: "chips", role: "group", "aria-label": "Risk levels" }, chips));
  }

  function renderTop() {
    const route = selectedRoute();
    const top = [...route.stops].sort((a, b) => b.share - a.share).filter((stop) => stop.share > 0).slice(0, 3);
    if (!top.length) { topEl.replaceChildren(); return; }
    topEl.replaceChildren(h("div", { class: "card top-card" },
      h("h3", { style: "margin-top:0" }, `What drives ${route.label}'s score`),
      h("p", { class: "muted small", style: "margin-top:0" }, `The three biggest contributors make up ${route.topShare}% of the score.`),
      h("ol", { class: "top3" }, top.map((stop) => h("li", {},
        h("button", { type: "button", class: "link-button", onclick: () => openNode(stop.id, true) },
          h("span", { class: "street-main" }, splitStreets(stop.label)[0]),
          splitStreets(stop.label)[1] ? h("span", { class: "street-cross" }, ` & ${splitStreets(stop.label)[1]}`) : null),
        h("span", { class: "muted" }, ` · ${stop.share}% of the score · ${stop.index.toFixed(1)}× average`))))));
  }

  const sidewalkText = { yes: "Sidewalk", partial: "Sidewalk on some sides", no: "No sidewalk", unknown: "Sidewalk not mapped" };
  const bikeText = { protected: "Protected bike lane", lane: "Bike lane", shared: "Shared bike route", none: "No bike lane", yes: "Bike lane" };
  const MAX_ROWS = 150;

  // `animate` staggers the rows in. Selecting a row doesn't rebuild the list (see markSelectedStop).
  function renderList(animate = false) {
    const route = selectedRoute();
    let stops = route.stops.filter((stop) => memory.tiers.has(stop.tier));
    if (memory.sort === "risk") stops = [...stops].sort((a, b) => b.share - a.share);
    const total = stops.length;
    const sortButtons = [["route", "Along the route"], ["risk", "Biggest contributors first"]].map(([key, label]) => {
      const button = h("button", { type: "button", class: "chip", "aria-pressed": memory.sort === key ? "true" : "false" }, label);
      button.addEventListener("click", () => { memory.sort = key; renderList(true); });
      return button;
    });
    let body;
    if (memory.tiers.size === 0) body = h("div", { class: "banner banner-info" }, "Choose at least one risk level above.");
    else if (total === 0) body = h("div", { class: "banner banner-info" }, `${route.label} passes no intersections at the chosen risk levels.`);
    else {
      const shown = stops.slice(0, MAX_ROWS);
      body = h("ul", { class: `stop-list${animate ? " is-entering" : ""}` }, shown.map((stop, i) => {
        const [main, cross] = splitStreets(stop.label);
        const chips = [
          h("span", { class: "mini-chip" }, tierPill(stop.tier)),
          stop.speed === null ? null : h("span", { class: "mini-chip" }, `${stop.speed} mph`),
          stop.signal === null ? null : h("span", { class: "mini-chip" }, stop.signal ? "Signal" : "No signal mapped"),
          h("span", { class: "mini-chip" }, sidewalkText[stop.sidewalk] || sidewalkText.unknown),
          memory.trip.mode === "BICYCLE" && bikeText[stop.bike] ? h("span", { class: "mini-chip" }, bikeText[stop.bike]) : null,
          stop.unvalidated ? h("span", { class: "mini-chip warn" }, "Unvalidated") : null,
          stop.reported ? h("span", { class: "mini-chip warn" }, icon("flag", 14), "You reported this") : null,
        ];
        const selected = memory.node === stop.id;
        return h("li", { style: `--i:${Math.min(i, 16)}` }, h("button", { type: "button", class: `stop${selected ? " selected" : ""}`, dataset: { id: String(stop.id) }, onclick: () => openNode(stop.id, true), "aria-label": `${stop.label}, ${TIER_SHORT[stop.tier]}, ${stop.share}% of the score` },
          h("span", { class: "stop-bar", style: `background:${TIER_COLORS[stop.tier]}`, "aria-hidden": "true" }),
          h("span", { class: "stop-main" },
            h("span", { class: "street-main" }, main), cross ? h("span", { class: "street-cross" }, `& ${cross}`) : null,
            h("span", { class: "stop-chips" }, chips)),
          h("span", { class: "stop-side" }, h("span", { class: "stop-share" }, `${stop.share}%`), h("span", { class: "muted small" }, `mile ${stop.miles.toFixed(1)}`))));
      }));
      if (total > shown.length) body = h("div", {}, body, h("p", { class: "muted small" }, `Showing the first ${shown.length} of ${total}. Narrow the risk levels above to see fewer.`));
    }
    listEl.replaceChildren(
      h("div", { class: "list-head" }, h("span", { class: "muted small" }, `${total} intersection${total === 1 ? "" : "s"}`), h("div", { class: "chips" }, sortButtons)),
      body,
      h("p", { class: "muted small" }, "The percentage is each intersection's share of this route's risk score."));
  }

  function markSelectedStop() {
    listEl.querySelectorAll(".stop").forEach((row) => row.classList.toggle("selected", row.dataset.id === String(memory.node)));
  }

  function closeSheet() {
    detailToken += 1;
    memory.node = null;
    hideSheet(sheetHost);
    if (tripMap) tripMap.selectNode(null);
    markSelectedStop();
  }

  // "8% of Route A's risk score · mile 2.3", or which routes pass it when it isn't on the selected one.
  function stopContext(id) {
    const route = selectedRoute();
    const stop = route.stops.find((item) => item.id === id);
    if (stop) return `${stop.share}% of ${route.label}'s risk score · mile ${stop.miles.toFixed(1)}`;
    const dot = memory.trip.map.dots.find((item) => item.id === id);
    return dot && dot.routes.length ? `On ${dot.routes.join(" and ")}` : null;
  }

  function stopLabel(id) {
    for (const route of memory.trip.routes) {
      const stop = route.stops.find((item) => item.id === id);
      if (stop) return stop.label;
    }
    return "Intersection";
  }

  // Tapping a dot shows the intersection in a popup on the map itself; "All details" opens the full panel.
  async function showOnMap(id) {
    if (!tripMap) { openNode(id, false); return; }
    memory.node = id;
    const mine = ++detailToken;
    hideSheet(sheetHost);
    tripMap.selectNode(id);
    markSelectedStop();
    tripMap.showNodeInfo(id, summaryMessage(stopLabel(id), "Loading details..."));
    try {
      const detail = await api.getIntersection(id);
      if (destroyed || mine !== detailToken || !tripMap) return;
      tripMap.showNodeInfo(id, renderIntersectionSummary(detail, { extra: stopContext(id), onMore: () => openNode(id, false) }));
    } catch (problem) {
      if (!destroyed && mine === detailToken && tripMap) tripMap.showNodeInfo(id, summaryMessage(stopLabel(id), problem.message));
    }
  }

  function onPopupClosed(id) {
    if (memory.node !== id || sheetHost.querySelector(".sheet:not(.is-leaving)")) return;
    memory.node = null;
    if (tripMap) tripMap.selectNode(null);
    markSelectedStop();
  }

  async function openNode(id, pan) {
    memory.node = id;
    const mine = ++detailToken;
    if (tripMap) { tripMap.closeNodeInfo(); tripMap.selectNode(id); if (pan) tripMap.focusNode(id); }
    markSelectedStop();
    showSheet(sheetHost, loadingBody());
    try {
      const detail = await api.getIntersection(id);
      if (destroyed || mine !== detailToken) return;
      const sheet = showSheet(sheetHost, renderIntersectionDetail(detail, { onClose: closeSheet, reported: Boolean(getReport(id)) }));
      const closeButton = sheet.querySelector(".sheet-close");
      if (closeButton) closeButton.focus({ preventScroll: true });
    } catch (problem) {
      if (!destroyed && mine === detailToken) showSheet(sheetHost, errorBody(problem.message, closeSheet), { role: "alert" });
    }
  }

  function renderResults(moveFocus) {
    if (tripMap) { tripMap.destroy(); tripMap = null; }
    unsubscribeAuth();
    sheetHost.replaceChildren();
    const trip = memory.trip;
    if (!trip) { resultsEl.replaceChildren(); return; }

    resultsHeading = h("h2", { tabindex: "-1" }, "Route options");
    const mapHolder = h("div", {}, h("div", { class: "map map-loading", "aria-hidden": "true" }, "Loading map"));
    const mapMessage = h("div", {});
    const pieces = [resultsHeading];
    trip.notices.forEach((notice) => pieces.push(h("div", { class: "banner banner-info" }, notice)));
    if (trip.warnings.outside) {
      pieces.push(h("div", { class: "banner banner-warn", role: "alert" },
        h("strong", {}, "Much of this trip is outside the areas SafeCross covers (New York City and Westchester County)."),
        " The intersection counts below are incomplete and should not be used to compare these routes."));
    } else if (trip.warnings.lowCoverage !== null) {
      pieces.push(h("div", { class: "banner banner-warn" }, `Only about ${Math.round(trip.warnings.lowCoverage * 100)}% of the least-covered route is inside SafeCross's areas, so its score may be low.`));
    }
    if (trip.warnings.unvalidated) {
      pieces.push(h("div", { class: "banner banner-warn", role: "alert" },
        h("strong", {}, "Part of this trip is in Westchester County, where rankings are unvalidated estimates."),
        " There is no crash history there, so Westchester intersections are ranked on road design alone, against each other rather than against New York City. Treat Westchester scores as a rough guide only."));
    }
    if (trip.avoid && trip.avoid.allPass) {
      pieces.push(h("div", { class: "banner banner-warn", role: "alert" },
        h("strong", {}, "Every route option passes an intersection you reported."),
        " SafeCross can only choose among the routes Google suggests, and Google can't be told to skip one intersection. Try a nearby start or destination, or another travel mode."));
    }
    if (trip.mode === "WALK" || trip.mode === "BICYCLE") {
      const who = trip.mode === "WALK" ? "pedestrian" : "cyclist";
      pieces.push(h("div", { class: "banner banner-info" }, `For this travel mode, intersections count a little more where the speed limit is high or a ${who} was hurt in the last eight weeks.`));
    }
    pieces.push(h("p", { class: "headline" }, boldParts(trip.headline)), cardsEl, mapsBar, mapMessage, mapHolder,
      h("div", { class: "legend" },
        TIER_NAMES.map((name, code) => h("span", {}, h("span", { class: "dot", style: `background:${TIER_COLORS[code]}` }), name)),
        h("span", {}, "Tap a dot for that intersection's details, or a route line or card to select the route.")),
      topEl, filtersEl, listEl, sheetHost,
      h("details", {}, h("summary", {}, "How is the risk score worked out?"),
        h("ul", {},
          h("li", {}, "Google's route line is matched against every scored intersection. An intersection counts as passed if it is within about 25 metres of the line, and counts more the closer the line runs to its centre."),
          h("li", {}, "Each intersection gets a relative risk: the model's prediction divided by the average for the intersections around it (about the surrounding kilometre), so 1.0 is typical for its neighbourhood and 3.0 is three times that. The model already weighs the intersection's recent and long-run crash history, crashes at nearby intersections, its speed limit, lanes, signal, crossings and one-way streets."),
          h("li", {}, "The route score adds up the relative risk of every intersection passed, not just the worst ones, so a long route through many average intersections can outscore a short route past one bad one. Lower is safer. Hot spots are intersections at least 3 times their neighbourhood's average."),
          h("li", {}, "Walking and cycling count intersections a little more where traffic is fast (26 mph and up, more at 35 mph and up) or where someone on foot or on a bike was hurt in the last eight weeks. These adjustments are judgement calls, not fitted to data."),
          h("li", {}, "Scores compare options for the same trip. They are not chances of a crash, and the model scores intersections only, so risk between intersections is not counted."),
          h("li", {}, "Large intersections can be counted more than once, and routes on bridges or highways can pick up streets they cross over or under."),
          h("li", {}, `Risk uses a recent weekly snapshot${trip.snapshotWeek ? ` (week of ${trip.snapshotWeek})` : ""}, not live conditions.`),
          h("li", {}, "In New York City, speed limits and bike lanes come from NYC DOT and sidewalks from the city's planimetric map. Street lighting, and everything in Westchester, comes from OpenStreetMap volunteers: 'not mapped' there means nobody has recorded it, not that it is missing."),
          h("li", {}, "Westchester County is an unvalidated estimate: the model was trained on New York City crashes and applied there to the road layout only."))),
      h("p", { class: "muted small" }, "Route options, travel times and the map are provided by Google Maps Platform. Risk rankings are from the SafeCross AI model. See About for terms and privacy."));
    pieces.forEach((piece, i) => piece.style.setProperty("--i", String(Math.min(i, 10))));
    resultsEl.replaceChildren(...pieces);
    renderCards();
    renderMapsLink();
    renderFilters();
    renderTop();
    renderList(true);
    if (moveFocus) resultsHeading.focus();

    unsubscribeAuth = onMapsAuthFailure((message) => mapMessage.replaceChildren(h("div", { class: "banner banner-error", role: "alert" }, message)));
    mountSharedMap(config.mapsJsKey, mapHolder).then(({ maps, map }) => {
      if (destroyed || memory.trip !== trip) return;
      tripMap = createTripMap({ maps, map, trip, onSelectRoute: select, onSelectNode: showOnMap, onInfoClosed: onPopupClosed });
      tripMap.setTiers(memory.tiers);
      tripMap.highlight(memory.selected);
      if (memory.node) tripMap.selectNode(memory.node);
    }).catch((problem) => {
      if (destroyed) return;
      mapMessage.replaceChildren(h("div", { class: "banner banner-error", role: "alert" }, describeMapsError(problem)));
    });
  }

  // A tour's "Try an example" request, or results kept from before the user visited another tab.
  if (ctx.takePendingExample && ctx.takePendingExample()) runExample();
  else if (memory.trip) renderResults(false);

  return {
    heading,
    destroy() {
      destroyed = true;
      unsubscribeAuth();
      if (tripMap) tripMap.destroy();
    },
  };
}
