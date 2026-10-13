// Talks to the SafeCross server. Nothing from /api is ever cached by the app or the service worker:
// route results are Google Maps Platform content, and caching them is restricted.
export class ApiError extends Error {
  constructor(message, status, kind) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.kind = kind; // "offline" | "network" | "server"
  }
}

async function request(path, { method = "GET", body } = {}) {
  if (typeof navigator !== "undefined" && navigator.onLine === false) {
    throw new ApiError("You're offline. Connect to the internet to use this.", 0, "offline");
  }
  let response;
  try {
    response = await fetch(path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      cache: "no-store",
    });
  } catch {
    throw new ApiError("Couldn't reach the server. Check your connection and try again.", 0, "network");
  }
  let data = null;
  try { data = await response.json(); } catch { /* not JSON */ }
  if (!response.ok) {
    // The service worker answers {"error":"offline"} (503) when the network is gone.
    if (response.status === 503 && data && data.error === "offline") {
      throw new ApiError("You're offline. Connect to the internet to use this.", 503, "offline");
    }
    throw new ApiError((data && data.error) || `The server returned an error (${response.status}).`, response.status, "server");
  }
  return data;
}

const query = (params) =>
  new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null)).toString();

export const getConfig = () => request("/api/config");
export const findRoutes = (body) => request("/api/routes", { method: "POST", body });
export const exploreGrid = (filters) => request(`/api/explore/grid?${query(filters)}`);
export const explorePoints = (params) => request(`/api/explore/points?${query(params)}`);
export const getIntersection = (id) => request(`/api/intersections/${encodeURIComponent(id)}`);
export const getModelInfo = () => request("/api/model");
