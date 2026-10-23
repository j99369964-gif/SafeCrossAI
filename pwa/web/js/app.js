// SafeCross AI: app shell. Hash router, service-worker registration (with an "update ready" prompt), offline banner,
// install button, and the first-run tour.
import { h, clear, hydrateIcons, reducedMotion } from "./dom.js";
import * as api from "./api.js";
import { mountHomeView } from "./homeview.js";
import { mountRouteView } from "./routeview.js";
import { mountExploreView } from "./exploreview.js";
import { mountReportView } from "./reportview.js";
import { openTour, shouldAutoOpen } from "./onboarding.js";
import { initInstall } from "./install.js";

const $ = (id) => document.getElementById(id);
const viewRoot = $("view");
const state = { config: null, current: null, route: null, pendingExample: false, tourOpen: false };

// ---------------------------------------------------------------------- toast
function hideToast() {
  const toast = $("toast");
  if (toast.hidden || reducedMotion()) { toast.hidden = true; return Promise.resolve(); }
  return new Promise((resolve) => {
    const done = () => { toast.classList.remove("is-leaving"); toast.hidden = true; resolve(); };
    toast.classList.add("is-leaving");
    toast.addEventListener("animationend", done, { once: true });
    setTimeout(done, 300);
  });
}

function showToast(text, actionLabel, onAction) {
  $("toast-text").textContent = text;
  const action = $("toast-action");
  action.textContent = actionLabel;
  action.onclick = () => { hideToast().then(onAction); };
  $("toast").hidden = false;
}

// ---------------------------------------------------------------------- service worker
export function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) return;
  const hadController = Boolean(navigator.serviceWorker.controller);
  let reloading = false;
  // Reload once when an updated worker takes over. Skipped on the very first install, which would be a pointless reload.
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (!hadController || reloading) return;
    reloading = true;
    window.location.reload();
  });
  const offerUpdate = (worker) => showToast("A new version is ready.", "Refresh", () => worker.postMessage({ type: "SKIP_WAITING" }));
  const register = async () => {
    try {
      const registration = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
      if (registration.waiting && navigator.serviceWorker.controller) offerUpdate(registration.waiting);
      registration.addEventListener("updatefound", () => {
        const worker = registration.installing;
        if (!worker) return;
        worker.addEventListener("statechange", () => {
          if (worker.state === "installed" && navigator.serviceWorker.controller) offerUpdate(worker);
        });
      });
    } catch {
      /* the app still works without a service worker; it just isn't available offline */
    }
  };
  if (document.readyState === "complete") register();
  else window.addEventListener("load", register);
}

// ---------------------------------------------------------------------- pages
function renderAbout(root) {
  const fragment = $("tpl-about").content.cloneNode(true);
  root.append(fragment);
  const heading = root.querySelector("h1");
  const contact = state.config && state.config.contactEmail;
  const placeholder = !contact || /example\.com$/i.test(contact);
  root.querySelector("[data-contact]").textContent = contact || "your-email@example.com";
  if (!placeholder) root.querySelector("#legal-draft").hidden = true;
  const version = state.config && state.config.version;
  if (version) Object.assign(root.querySelector("[data-version]"), { textContent: `Version ${version}`, hidden: false });

  const modelInfo = root.querySelector("#model-info");
  api.getModelInfo().then((info) => {
    const metrics = info.testMetrics && typeof info.testMetrics === "object"
      ? Object.entries(info.testMetrics).filter(([, value]) => typeof value === "number").slice(0, 8) : [];
    modelInfo.replaceChildren(
      h("div", { class: "banner banner-warn" }, "These results describe New York City only. Westchester County has no crash data in this project, so none of these numbers apply to it."),
      info.selectedModel ? h("p", {}, "Selected model: ", h("strong", {}, String(info.selectedModel)), info.snapshotWeek ? ` · risk snapshot week of ${info.snapshotWeek}` : "") : null,
      metrics.length ? h("dl", { class: "kv" }, metrics.flatMap(([name, value]) => [h("dt", {}, name.replace(/_/g, " ")), h("dd", {}, String(Math.round(value * 1000) / 1000))]))
        : h("p", { class: "muted" }, "Detailed test metrics aren't published with this deployment."));
  }).catch((problem) => modelInfo.replaceChildren(h("p", { class: "muted" }, problem.message)));
  return { heading, destroy() {} };
}

const PAGES = {
  home: { title: "Home", mount: (root) => mountHomeView(root) },
  route: { title: "Plan a safer route", mount: (root, ctx) => mountRouteView(root, ctx) },
  explore: { title: "Explore the risk map", mount: (root, ctx) => mountExploreView(root, ctx) },
  report: { title: "Report a dangerous intersection", mount: (root) => mountReportView(root) },
  about: { title: "About", mount: (root) => renderAbout(root) },
};

function currentRouteName() {
  const match = /^#\/([a-z]+)/.exec(window.location.hash || "");
  if (!match) return "home";
  if (match[1] === "legal") return "about"; // old/shared links to the terms land on About
  return PAGES[match[1]] ? match[1] : "home";
}

function highlightNav(name) {
  document.querySelectorAll("[data-route]").forEach((link) => {
    if (link.dataset.route === name) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  placeNavIndicators();
}

// The amber underline (top bar) and the pill (bottom bar) slide to the current tab. The first placement is instant.
function placeNavIndicators() {
  document.querySelectorAll(".nav-indicator").forEach((indicator) => {
    const nav = indicator.parentElement;
    const link = nav.querySelector('[aria-current="page"]');
    const box = link && link.getBoundingClientRect();
    if (!box || !box.width) return; // this nav is hidden at the current screen width
    indicator.style.setProperty("--x", `${box.left - nav.getBoundingClientRect().left}px`);
    indicator.style.setProperty("--w", `${box.width}px`);
    if (!indicator.classList.contains("is-placed")) requestAnimationFrame(() => indicator.classList.add("is-placed"));
  });
}

const context = {
  get config() { return state.config; },
  takePendingExample() { const value = state.pendingExample; state.pendingExample = false; return value; },
};

function offlineScreen(message) {
  clear(viewRoot);
  viewRoot.append(h("section", { class: "page" }, h("h1", { tabindex: "-1" }, "SafeCross AI"),
    h("div", { class: "banner banner-offline", style: "border-radius:12px;justify-content:space-between" }, message,
      h("button", { type: "button", class: "btn btn-small", onclick: () => navigate() }, "Try again"))));
}

export async function navigate() {
  const name = currentRouteName();
  if (state.current) { state.current.destroy(); state.current = null; }
  clear(viewRoot);
  highlightNav(name);
  document.title = `${PAGES[name].title} · SafeCross AI`;
  state.route = name;

  if (!state.config) {
    try { state.config = await api.getConfig(); }
    catch (problem) { offlineScreen(problem.kind === "offline" || problem.kind === "network" ? "Can't reach the server right now. Check your connection." : problem.message); return; }
    if (currentRouteName() !== name) return; // the user moved on while we were loading
  }
  state.current = PAGES[name].mount(viewRoot, context);
  if (state.current && state.current.heading) state.current.heading.focus();
  if (window.location.hash === "#/legal") { const legal = document.getElementById("legal"); if (legal) legal.scrollIntoView(); }
  // The tour opens the first time the visitor reaches the route planner, not on the home page.
  if (name === "route" && !state.tourOpen && shouldAutoOpen(window.location.search)) startTour(0);
}

// ---------------------------------------------------------------------- tour
function startTour(startStep = 0) {
  if (state.tourOpen) return;
  state.tourOpen = true;
  openTour({
    host: $("overlay-root"),
    startStep,
    onClose: ({ example }) => {
      state.tourOpen = false;
      if (!example) return;
      state.pendingExample = true;
      if (state.route === "route") navigate(); // already here: remount so the example runs
      else window.location.hash = "#/route";
    },
  });
}

// ---------------------------------------------------------------------- online / offline
function syncOnline() { $("offline-banner").hidden = navigator.onLine !== false; }

// ---------------------------------------------------------------------- boot
export function boot() {
  hydrateIcons(document.body);
  window.addEventListener("hashchange", () => navigate());
  window.addEventListener("resize", placeNavIndicators);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(placeNavIndicators); // web fonts change tab widths
  window.addEventListener("online", syncOnline);
  window.addEventListener("offline", syncOnline);
  syncOnline();
  $("help-button").addEventListener("click", () => startTour(0));
  initInstall({ button: $("install-button"), iosHint: $("ios-hint"), iosDismiss: $("ios-hint-dismiss") });
  registerServiceWorker();
  navigate();
}

boot();
