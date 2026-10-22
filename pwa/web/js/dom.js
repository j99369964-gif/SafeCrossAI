// Tiny DOM helper. Elements are built from text nodes and attributes only; nothing here ever parses HTML,
// so text from the server or the user can never become markup.
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "dataset") Object.assign(el.dataset, value);
    else if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2).toLowerCase(), value);
    else el.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(typeof child === "object" && child.nodeType ? child : document.createTextNode(String(child)));
  }
  return el;
}

export function clear(el) {
  el.replaceChildren();
  return el;
}

// "a **b** c" parts from the server -> text with <strong>, still without parsing HTML.
export function boldParts(parts) {
  return parts.map(([text, bold]) => (bold ? h("strong", {}, text) : text));
}

// ---------------------------------------------------------------------- icons
// 24x24 stroke icons, each a list of [tag, attributes]. Built with createElementNS, so still no HTML parsing.
const SVG_NS = "http://www.w3.org/2000/svg";
const ICONS = {
  home: [["path", { d: "M4 10.5 12 4l8 6.5V20h-5.5v-5.5h-5V20H4z" }]],
  route: [["circle", { cx: 6, cy: 18, r: 2.5 }], ["circle", { cx: 18, cy: 6, r: 2.5 }], ["path", { d: "M8.5 18H15a3 3 0 0 0 0-6H9a3 3 0 0 1 0-6h6.5" }]],
  map: [["path", { d: "M3 6.5 9 4l6 2.5L21 4v13.5L15 20l-6-2.5L3 20z" }], ["path", { d: "M9 4v13.5M15 6.5V20" }]],
  info: [["circle", { cx: 12, cy: 12, r: 9 }], ["path", { d: "M12 11v5.5M12 7.6v.01" }]],
  help: [["circle", { cx: 12, cy: 12, r: 9 }], ["path", { d: "M9.6 9.4a2.5 2.5 0 1 1 3.4 2.4c-.6.3-1 .8-1 1.5v.4M12 17v.01" }]],
  car: [["path", { d: "M4 16.5V12l2.3-5h11.4l2.3 5v4.5z" }], ["path", { d: "M4 12h16" }], ["circle", { cx: 7.5, cy: 16.5, r: 1.6 }], ["circle", { cx: 16.5, cy: 16.5, r: 1.6 }]],
  bike: [["circle", { cx: 6, cy: 16, r: 3.5 }], ["circle", { cx: 18, cy: 16, r: 3.5 }], ["path", { d: "M6 16l3.5-7h5.5L18 16M9.5 9 12 16M13.5 6h2.5l-1 3" }]],
  walk: [["circle", { cx: 13, cy: 4.5, r: 1.8 }], ["path", { d: "m10 21 2-6-2.5-2.5 1.2-4.5 2.8 2.5H17M9.7 8.5 7 11v3M12 15l2.5 2.2V21" }]],
  locate: [["circle", { cx: 12, cy: 12, r: 4 }], ["path", { d: "M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3" }]],
  close: [["path", { d: "M6 6l12 12M18 6 6 18" }]],
  arrow: [["path", { d: "M5 12h14M13 6l6 6-6 6" }]],
  external: [["path", { d: "M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" }]],
  download: [["path", { d: "M12 4v11M7 10l5 5 5-5M5 20h14" }]],
  database: [["ellipse", { cx: 12, cy: 6, rx: 7, ry: 2.8 }], ["path", { d: "M5 6v12c0 1.5 3.1 2.8 7 2.8s7-1.3 7-2.8V6M5 12c0 1.5 3.1 2.8 7 2.8s7-1.3 7-2.8" }]],
  cloud: [["path", { d: "M7 18h10.5a3.5 3.5 0 0 0 .4-7A5.5 5.5 0 0 0 7.3 9.6 4.2 4.2 0 0 0 7 18z" }]],
  heart: [["path", { d: "M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z" }]],
  users: [["circle", { cx: 9, cy: 8, r: 3 }], ["path", { d: "M3.5 19a5.5 5.5 0 0 1 11 0M16 5.2a3 3 0 0 1 0 5.6M17.5 14a5 5 0 0 1 3 5" }]],
  lock: [["rect", { x: 5, y: 11, width: 14, height: 9, rx: 2 }], ["path", { d: "M8 11V8a4 4 0 0 1 8 0v3" }]],
  flag: [["path", { d: "M5 21V4M5 4h11l-2 4 2 4H5" }]],
  check: [["path", { d: "m5 12.5 4.5 4.5L19 7.5" }]],
  search: [["circle", { cx: 10.5, cy: 10.5, r: 6 }], ["path", { d: "m15 15 5 5" }]],
  road: [["path", { d: "M8 3 4 21M16 3l4 18M12 4v3M12 10.5v3M12 17v3" }]],
  trash: [["path", { d: "M4.5 7h15M10 4h4M6.5 7l1 13h9l1-13M10 11v6M14 11v6" }]],
  copy: [["rect", { x: 8, y: 8, width: 12, height: 12, rx: 2 }], ["path", { d: "M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3" }]],
  share: [["circle", { cx: 6, cy: 12, r: 2.5 }], ["circle", { cx: 18, cy: 6, r: 2.5 }], ["circle", { cx: 18, cy: 18, r: 2.5 }], ["path", { d: "m8.3 10.8 7.4-3.6M8.3 13.2l7.4 3.6" }]],
  phone: [["path", { d: "M5 4h3.5l1.5 4.5-2.2 1.4a11 11 0 0 0 6.3 6.3l1.4-2.2L20 15.5V19a1 1 0 0 1-1 1A15 15 0 0 1 4 5a1 1 0 0 1 1-1z" }]],
  mail: [["rect", { x: 3.5, y: 5.5, width: 17, height: 13, rx: 2 }], ["path", { d: "m4 7 8 6 8-6" }]],
};

export function icon(name, size = 20) {
  const svg = document.createElementNS(SVG_NS, "svg");
  for (const [key, value] of Object.entries({ viewBox: "0 0 24 24", width: size, height: size, fill: "none", stroke: "currentColor",
    "stroke-width": 1.8, "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true", focusable: "false", class: "icon" })) {
    svg.setAttribute(key, String(value));
  }
  for (const [tag, attrs] of ICONS[name] || []) {
    const part = document.createElementNS(SVG_NS, tag);
    for (const [key, value] of Object.entries(attrs)) part.setAttribute(key, String(value));
    svg.append(part);
  }
  return svg;
}

/** Fills every `<span data-icon="name">` under `root` with that icon (used by the static HTML). */
export function hydrateIcons(root) {
  root.querySelectorAll("[data-icon]").forEach((slot) => {
    if (!slot.firstElementChild) slot.append(icon(slot.dataset.icon, Number(slot.dataset.size) || 20));
  });
}

// ---------------------------------------------------------------------- page header
/** Kicker line, big focusable h1, and a lede. Returns { header, heading }. */
export function pageHeader(kicker, title, lede) {
  const heading = h("h1", { tabindex: "-1" }, title);
  const header = h("header", { class: "page-head" }, h("p", { class: "kicker" }, kicker), heading, lede ? h("p", { class: "lede" }, lede) : null);
  return { header, heading };
}

// ---------------------------------------------------------------------- motion
export const reducedMotion = () => Boolean(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);

/** Plays the element's `.is-leaving` exit animation, then removes it. Resolves once it is gone. */
export function leave(el, fallbackMs = 320) {
  if (!el || !el.isConnected) return Promise.resolve();
  if (reducedMotion()) { el.remove(); return Promise.resolve(); }
  return new Promise((resolve) => {
    let done = false;
    const finish = () => { if (done) return; done = true; el.remove(); resolve(); };
    el.classList.add("is-leaving");
    el.addEventListener("animationend", (event) => { if (event.target === el) finish(); });
    setTimeout(finish, fallbackMs); // in case the animation never runs (hidden tab, no CSS)
  });
}

/** Animates the text of `el` from 0 up to `value`, keeping `decimals` places. */
export function countUp(el, value, decimals = 0, duration = 700) {
  const format = (n) => n.toFixed(decimals);
  if (reducedMotion() || !Number.isFinite(value)) { el.textContent = format(value); return; }
  const start = performance.now();
  const step = (now) => {
    const t = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - t, 3);
    el.textContent = format(value * eased);
    if (t < 1 && el.isConnected) requestAnimationFrame(step);
  };
  el.textContent = format(0);
  requestAnimationFrame(step);
}
