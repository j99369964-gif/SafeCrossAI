// Street / intersection search box (an ARIA combobox). Used on the Explore map and on the report page.
// Results come from /api/search: { type: "street", key, part, name, area, count, from, to }
// or { type: "intersection", id, label, area, tier, ... }.
import { h, icon } from "./dom.js";
import * as api from "./api.js";
import { TIER_COLORS, TIER_SHORT } from "./detail.js";

const DEBOUNCE_MS = 200;
let instances = 0;

/** "New York City · 31 intersections · West 30th Street to West 60th Street" */
export function streetSubtitle(street) {
  const parts = [street.area, `${street.count.toLocaleString()} intersection${street.count === 1 ? "" : "s"}`];
  if (street.from && street.to) parts.push(`${street.from} to ${street.to}`);
  else if (street.from) parts.push(`at ${street.from}`);
  return parts.filter(Boolean).join(" · ");
}

/**
 * `onPick(result)` runs when a result is chosen. `only: "intersection"` hides street results (the report page needs
 * one intersection). Returns { element, input, clear() }.
 */
export function createSearchBox({ label, placeholder, onPick, only = null, hint = null }) {
  const n = ++instances;
  const listId = `search-results-${n}`;
  const inputId = `search-input-${n}`;
  const input = h("input", {
    type: "search", id: inputId, autocomplete: "off", spellcheck: "false", enterkeyhint: "search", placeholder,
    role: "combobox", "aria-autocomplete": "list", "aria-expanded": "false", "aria-controls": listId,
  });
  const list = h("ul", { id: listId, class: "search-results", role: "listbox", "aria-label": "Search results", hidden: true });
  const status = h("p", { class: "visually-hidden", role: "status", "aria-live": "polite" });
  const clearButton = h("button", { type: "button", class: "input-action", "aria-label": "Clear search", title: "Clear", hidden: true, onclick: () => { clear(); input.focus(); } }, icon("close", 18));
  const element = h("div", { class: "search-box" },
    h("label", { for: inputId }, label),
    h("div", { class: "field search-field" }, h("span", { class: "search-icon", "aria-hidden": "true" }, icon("search", 18)), input, clearButton),
    list, status, hint ? h("p", { class: "form-hint search-hint" }, hint) : null);

  let results = [];
  let active = -1;
  let timer = null;
  let token = 0;

  function close() {
    list.hidden = true;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    active = -1;
  }

  function setActive(index) {
    active = index;
    [...list.children].forEach((item, i) => item.setAttribute("aria-selected", i === index ? "true" : "false"));
    const item = list.children[index];
    if (item && item.id) { input.setAttribute("aria-activedescendant", item.id); item.scrollIntoView({ block: "nearest" }); }
    else input.removeAttribute("aria-activedescendant");
  }

  function pick(index) {
    const result = results[index];
    if (!result) return;
    input.value = result.type === "street" ? result.name : result.label;
    clearButton.hidden = false;
    close();
    onPick(result);
  }

  function option(result, index) {
    const body = result.type === "street"
      ? [h("span", { class: "result-icon", "aria-hidden": "true" }, icon("road", 18)),
        h("span", { class: "result-text" }, h("span", { class: "result-title" }, result.name), h("span", { class: "result-sub" }, `Street · ${streetSubtitle(result)}`))]
      : [h("span", { class: "result-icon", "aria-hidden": "true" }, h("span", { class: "dot", style: `background:${TIER_COLORS[result.tier]}` })),
        h("span", { class: "result-text" }, h("span", { class: "result-title" }, result.label),
          h("span", { class: "result-sub" }, `Intersection · ${result.area}${result.unvalidated ? " (unvalidated)" : ""} · ${TIER_SHORT[result.tier]}${result.meters !== undefined ? ` · ${result.meters} m away` : ""}`))];
    return h("li", {
      id: `${listId}-${index}`, role: "option", "aria-selected": "false", class: "search-result",
      onmousedown: (event) => event.preventDefault(), // keep focus in the input
      onclick: () => pick(index),
    }, body);
  }

  function show(items, emptyText) {
    results = items;
    if (!items.length) {
      list.replaceChildren(h("li", { class: "search-empty", role: "presentation" }, emptyText));
      status.textContent = emptyText;
    } else {
      list.replaceChildren(...items.map(option));
      status.textContent = `${items.length} result${items.length === 1 ? "" : "s"}. Use the up and down arrows to choose.`;
    }
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
    setActive(items.length ? 0 : -1);
  }

  async function run(text) {
    const mine = ++token;
    try {
      const { results: found } = await api.search(text);
      if (mine !== token) return;
      let items = only ? found.filter((r) => r.type === only) : found;
      // On the report page a street alone isn't enough; nudge towards naming the cross street.
      const nudge = only === "intersection" && !items.length && found.length
        ? `Add the cross street, for example "${found[0].name} & ..."` : null;
      show(items, nudge || "No matching streets or intersections. Try another spelling, or add the cross street with \"&\".");
    } catch (problem) {
      if (mine === token) show([], problem.message);
    }
  }

  input.addEventListener("input", () => {
    clearTimeout(timer);
    const text = input.value.trim();
    clearButton.hidden = !input.value;
    if (text.length < 2) { token++; close(); return; }
    timer = setTimeout(() => run(text), DEBOUNCE_MS);
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (list.hidden) { if (input.value.trim().length >= 2) run(input.value.trim()); return; }
      event.preventDefault();
      if (!results.length) return;
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActive((active + step + results.length) % results.length);
    } else if (event.key === "Enter") {
      event.preventDefault();
      if (!list.hidden && results.length) pick(Math.max(active, 0));
      else if (input.value.trim().length >= 2) { clearTimeout(timer); run(input.value.trim()); }
    } else if (event.key === "Escape") {
      if (!list.hidden) { event.preventDefault(); close(); }
    }
  });
  input.addEventListener("blur", () => setTimeout(close, 120));

  function clear() {
    token++;
    clearTimeout(timer);
    input.value = "";
    clearButton.hidden = true;
    close();
  }

  return { element, input, clear };
}
