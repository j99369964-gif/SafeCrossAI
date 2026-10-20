// The intersection details panel, shared by the Explore map and the route results so both show the same thing.
// Built from text nodes only (see dom.js); nothing from the server is ever parsed as HTML.
import { h, icon, leave } from "./dom.js";

export const TIER_COLORS = ["#d7191c", "#fdae61", "#abd9e9", "#b5bdc6"];
export const TIER_NAMES = ["Highest-priority (top 10%)", "Elevated relative risk", "Moderate relative risk", "Lower relative risk"];
export const TIER_SHORT = ["High risk", "Elevated", "Moderate", "Lower"];

/** "Broadway & West 42nd Street" -> the two street names (or the whole label when there is no " & "). */
export function splitStreets(label) {
  const at = label.indexOf(" & ");
  return at === -1 ? [label, ""] : [label.slice(0, at), label.slice(at + 3)];
}

/** Two-line street title: the first street bold, the cross street underneath. */
export function streetTitle(label, tag = "h3") {
  const [first, second] = splitStreets(label);
  return h(tag, { class: "street-title" }, h("span", { class: "street-main" }, first), second ? h("span", { class: "street-cross" }, `& ${second}`) : null);
}

export function tierPill(code) {
  return h("span", { class: "tier-pill" }, h("span", { class: "dot", style: `background:${TIER_COLORS[code]}`, "aria-hidden": "true" }), TIER_SHORT[code]);
}

function ordinal(n) {
  const v = n % 100;
  if (v >= 11 && v <= 13) return `${n}th`;
  return `${n}${["th", "st", "nd", "rd"][n % 10 > 3 ? 0 : n % 10]}`;
}

function riskIndexText(detail) {
  const value = detail.riskIndex;
  if (value === null || value === undefined) return null;
  const scope = detail.validated ? detail.area : `${detail.area} (unvalidated)`;
  if (value >= 1.15) return `${value.toFixed(1)}× the average intersection in ${scope}`;
  if (value <= 0.85) return `${value.toFixed(1)}× the average intersection in ${scope} (below average)`;
  return `About the same as the average intersection in ${scope}`;
}

function factGroup(group) {
  return h("section", { class: "fact-group" },
    h("h4", {}, group.title),
    h("dl", { class: "facts" }, group.items.map((item) => h("div", { class: `fact tone-${item.tone}` },
      h("dt", {}, item.label),
      h("dd", {}, h("span", { class: "tone-dot", "aria-hidden": "true" }), h("span", {}, item.value,
        item.source ? h("span", { class: "fact-source" }, item.source) : null))))));
}

/** The full panel body for one intersection, from /api/intersections/<id>. */
export function renderIntersectionDetail(detail, { onClose } = {}) {
  const close = onClose ? h("button", { type: "button", class: "btn btn-small btn-ghost sheet-close", onclick: onClose, "aria-label": "Close details" }, icon("close", 18)) : null;
  const index = riskIndexText(detail);
  return h("div", { class: "detail" },
    h("div", { class: "detail-head" }, streetTitle(detail.label, "h3"), close),
    h("div", { class: "detail-risk" },
      tierPill(detail.tierCode),
      h("span", { class: "muted" }, `${ordinal(detail.percentile)} percentile among nearby intersections in ${detail.area}${detail.validated ? "" : " (unvalidated)"}`)),
    index ? h("p", { class: "detail-index" }, index) : null,
    detail.note ? h("div", { class: "banner banner-warn" }, detail.note.replaceAll("**", "")) : null,
    (detail.facts || []).map(factGroup),
    detail.signals && detail.signals.length ? h("section", { class: "fact-group" }, h("h4", {}, "What stands out"),
      h("ul", { class: "plain" }, detail.signals.map((signal) => h("li", {},
        `${signal.feature}: ${signal.value}${signal.percentile === null ? "" : ` (higher than ${signal.percentile}% of intersections in this area)`}`)))) : null,
    h("section", { class: "fact-group" }, h("h4", {}, "Rule-based items to review"),
      h("ul", { class: "plain" }, detail.measures.map((measure) => h("li", {}, measure))),
      h("p", { class: "muted small" }, "Rule-based suggestions for further review, not model output and not a recommendation.")));
}

// The facts the route map's popup shows, by the start of their label in /api/intersections/<id>.
const SUMMARY_FACTS = [["Speed limit", "Speed limit"], ["Traffic control", "Control"], ["Marked crosswalk", "Crosswalk"],
  ["Sidewalk", "Sidewalk"], ["Bike lane", "Bike lane"], ["Crashes, last 52 weeks", "Crashes, past year"]];

/**
 * A compact card for the popup on the route map: name, risk level, the key street facts, and `extra` (for example
 * the intersection's share of the route's score). `onMore` opens the full details panel.
 */
export function renderIntersectionSummary(detail, { extra, onMore } = {}) {
  const facts = (detail.facts || []).flatMap((group) => group.items);
  const rows = SUMMARY_FACTS.map(([prefix, label]) => {
    const fact = facts.find((item) => item.label.startsWith(prefix));
    return fact ? h("div", { class: `fact tone-${fact.tone}` }, h("dt", {}, label),
      h("dd", {}, h("span", { class: "tone-dot", "aria-hidden": "true" }), fact.value)) : null;
  }).filter(Boolean);
  const index = riskIndexText(detail);
  return h("div", { class: "map-popup", role: "dialog", "aria-label": `Intersection: ${detail.label}` },
    streetTitle(detail.label, "h3"),
    h("div", { class: "detail-risk" }, tierPill(detail.tierCode),
      h("span", {}, `${ordinal(detail.percentile)} percentile nearby${detail.validated ? "" : " (unvalidated)"}`)),
    index ? h("p", { class: "popup-index" }, index) : null,
    extra ? h("p", { class: "popup-extra" }, extra) : null,
    rows.length ? h("dl", { class: "facts" }, rows) : null,
    onMore ? h("button", { type: "button", class: "btn btn-small popup-more", onclick: onMore }, "All details", icon("arrow", 16)) : null);
}

/** What the popup shows while the details load, or if they can't. */
export const summaryMessage = (label, message) => h("div", { class: "map-popup" }, streetTitle(label, "h3"), h("p", { class: "popup-extra" }, message));

/** Loading and error bodies so callers do not repeat them. */
export const loadingBody = () => h("div", { class: "detail", "aria-busy": "true" },
  h("span", { class: "visually-hidden" }, "Loading..."),
  h("div", { class: "skeleton skeleton-title", "aria-hidden": "true" }),
  [100, 72, 88, 64, 80].map((width) => h("div", { class: "skeleton skeleton-line", style: `width:${width}%`, "aria-hidden": "true" })));
export function errorBody(message, onClose) {
  return h("div", { class: "detail", role: "alert" }, message, " ", h("button", { type: "button", class: "btn btn-small btn-ghost", onclick: onClose }, "Close"));
}

/**
 * Shows `body` in the details sheet inside `host`. An open sheet keeps its frame and only swaps its contents, so moving
 * between intersections doesn't replay the slide-in. Returns the sheet element.
 */
export function showSheet(host, body, { role = "dialog" } = {}) {
  let sheet = host.querySelector(".sheet:not(.is-leaving)");
  if (sheet) sheet.replaceChildren(body);
  else {
    sheet = h("div", { class: "sheet" }, body);
    host.append(sheet);
  }
  sheet.setAttribute("role", role);
  if (role === "dialog") sheet.setAttribute("aria-label", "Intersection details");
  else sheet.removeAttribute("aria-label");
  return sheet;
}

/** Slides the details sheet out, then removes it. */
export function hideSheet(host) {
  host.querySelectorAll(".sheet:not(.is-leaving)").forEach((sheet) => leave(sheet));
}
