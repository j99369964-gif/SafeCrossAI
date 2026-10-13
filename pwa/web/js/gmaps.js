// Loads the Google Maps JavaScript API ONCE and keeps ONE map instance for the whole session. Every `new google.maps.Map`
// is a billable map load, so views share the instance: the map element is moved into whichever page is showing.
import { h } from "./dom.js";

const SCRIPT_TIMEOUT_MS = 15000;
export const AUTH_MESSAGE =
  "Google Maps rejected the browser API key. Check that the Maps JavaScript API is enabled, billing is on, " +
  "and the key's website restrictions include this site.";

let loadPromise = null;
let authFailed = false;
const authListeners = new Set();
let sharedMap = null;
let sharedElement = null;

export function onMapsAuthFailure(listener) {
  authListeners.add(listener);
  if (authFailed) listener(AUTH_MESSAGE);
  return () => authListeners.delete(listener);
}

export function loadGoogleMaps(key) {
  if (window.google && window.google.maps) return Promise.resolve(window.google.maps);
  if (loadPromise) return loadPromise;
  loadPromise = new Promise((resolve, reject) => {
    const fail = (message) => { loadPromise = null; reject(new Error(message)); };
    // Google calls this if the key is rejected (API off, wrong referrer, billing...).
    window.gm_authFailure = () => {
      authFailed = true;
      authListeners.forEach((listener) => listener(AUTH_MESSAGE));
    };
    window.__safecrossMapsReady = () => resolve(window.google.maps);
    const script = h("script", {
      src: `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(key)}&callback=__safecrossMapsReady&loading=async&v=weekly`,
      async: true,
    });
    script.onerror = () => fail("Google Maps couldn't be loaded. Check your connection and try again.");
    document.head.append(script);
    setTimeout(() => { if (!(window.google && window.google.maps)) fail("Google Maps did not load in time. Check your connection."); }, SCRIPT_TIMEOUT_MS);
  });
  return loadPromise;
}

/** Puts the shared map inside `container` and returns { maps, map }. */
export async function mountSharedMap(key, container, options = {}) {
  const maps = await loadGoogleMaps(key);
  if (!sharedElement) sharedElement = h("div", { class: "map", id: "map", role: "region", "aria-label": "Map" });
  container.replaceChildren(sharedElement);
  if (!sharedMap) {
    sharedMap = new maps.Map(sharedElement, {
      center: options.center || { lat: 40.8, lng: -73.9 },
      zoom: options.zoom || 10,
      mapTypeControl: false,
      streetViewControl: false,
      clickableIcons: false,
      fullscreenControl: true,
    });
  } else {
    maps.event.trigger(sharedMap, "resize"); // the container may have a new size
  }
  return { maps, map: sharedMap };
}

export const metersForPixels = (map, pixels) => {
  // Metres covered by `pixels` screen pixels at the current zoom and latitude, so dots keep a constant on-screen size.
  const latitude = map.getCenter().lat();
  return (pixels * 156543.03392 * Math.cos((latitude * Math.PI) / 180)) / Math.pow(2, map.getZoom());
};

export function describeMapsError(error) {
  return error && error.message ? error.message : "The map couldn't be loaded.";
}
