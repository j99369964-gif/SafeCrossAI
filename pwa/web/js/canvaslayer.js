// Draws many map dots and squares on ONE canvas instead of one Google Maps shape each. Thousands of separate
// google.maps.Circle / Data-layer polygons make panning and zooming stutter; a canvas redraws them in a millisecond or two.
// The canvas covers the visible map plus a margin and moves with the map's panes, so a drag costs nothing until it
// passes the margin. Clicks and hover are hit-tested here, since a canvas has no per-shape events.
//
// Dots:  { lat, lng, r (px), fill, alpha, stroke, strokeAlpha, strokeWidth, z, data }  (higher z is drawn on top)
// Rects: { south, west, north, east, fill, alpha, stroke, strokeWidth, data }
const TILE = 256;
const worldX = (lng) => ((lng + 180) / 360) * TILE;
const worldY = (lat) => {
  const s = Math.min(Math.max(Math.sin((lat * Math.PI) / 180), -0.9999), 0.9999);
  return (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * TILE;
};
const coarsePointer = () => Boolean(window.matchMedia && window.matchMedia("(pointer: coarse)").matches);

export function createCanvasLayer(maps, map, { onClick } = {}) {
  const canvas = document.createElement("canvas");
  canvas.style.cssText = "position:absolute;pointer-events:none;z-index:100";
  const ctx = canvas.getContext("2d");
  let dots = [];
  let rects = [];
  let frame = 0;
  let view = null; // what the canvas currently covers: { left, top, width, height, zoom }
  let hovering = false;

  const overlay = new maps.OverlayView();
  overlay.onAdd = () => overlay.getPanes().overlayLayer.append(canvas);
  overlay.onRemove = () => canvas.remove();
  overlay.draw = () => render();

  // Where the map centre sits in the pane's pixel space, and how world coordinates map onto it.
  function frameOfReference() {
    const projection = overlay.getProjection();
    const center = map.getCenter();
    if (!projection || !center) return null;
    const pixel = projection.fromLatLngToDivPixel(center);
    const div = map.getDiv();
    return {
      cx: pixel.x, cy: pixel.y, wx: worldX(center.lng()), wy: worldY(center.lat()),
      scale: Math.pow(2, map.getZoom()), width: div.clientWidth, height: div.clientHeight,
    };
  }

  function render() {
    cancelAnimationFrame(frame);
    frame = 0;
    const ref = frameOfReference();
    if (!ref || !ref.width || !ref.height) return;
    const margin = Math.round(Math.max(ref.width, ref.height) / 3);
    const left = Math.round(ref.cx - ref.width / 2 - margin);
    const top = Math.round(ref.cy - ref.height / 2 - margin);
    const width = ref.width + 2 * margin;
    const height = ref.height + 2 * margin;
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
    }
    canvas.style.left = `${left}px`;
    canvas.style.top = `${top}px`;
    view = { left, top, width, height, zoom: map.getZoom() };

    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const offsetX = ref.cx - left - ref.wx * ref.scale;
    const offsetY = ref.cy - top - ref.wy * ref.scale;

    for (const rect of rects) {
      const x = rect.x0 * ref.scale + offsetX, y = rect.y0 * ref.scale + offsetY;
      const w = (rect.x1 - rect.x0) * ref.scale, h = (rect.y1 - rect.y0) * ref.scale;
      if (x > width || y > height || x + w < 0 || y + h < 0) continue;
      ctx.globalAlpha = rect.alpha;
      ctx.fillStyle = rect.fill;
      ctx.fillRect(x, y, w, h);
      if (rect.strokeWidth) {
        ctx.globalAlpha = 1;
        ctx.lineWidth = rect.strokeWidth;
        ctx.strokeStyle = rect.stroke;
        ctx.strokeRect(x, y, w, h);
      }
    }

    for (const dot of dots) {
      const x = dot.x * ref.scale + offsetX, y = dot.y * ref.scale + offsetY;
      if (x < -dot.r || y < -dot.r || x > width + dot.r || y > height + dot.r) continue;
      ctx.beginPath();
      ctx.arc(x, y, dot.r, 0, 2 * Math.PI);
      ctx.globalAlpha = dot.alpha;
      ctx.fillStyle = dot.fill;
      ctx.fill();
      if (dot.strokeWidth) {
        ctx.globalAlpha = dot.strokeAlpha;
        ctx.lineWidth = dot.strokeWidth;
        ctx.strokeStyle = dot.stroke;
        ctx.stroke();
      }
    }
    ctx.globalAlpha = 1;
  }

  const schedule = () => { if (!frame) frame = requestAnimationFrame(render); };

  // While dragging, the canvas rides along with the pane; redraw only once the visible map leaves the drawn area.
  function checkCoverage() {
    if (!view || frame) return;
    const ref = frameOfReference();
    if (!ref) return;
    const left = ref.cx - ref.width / 2, top = ref.cy - ref.height / 2;
    if (map.getZoom() !== view.zoom || left < view.left || top < view.top ||
        left + ref.width > view.left + view.width || top + ref.height > view.top + view.height) schedule();
  }

  /** The topmost dot (or else rect) under a map position, or null. */
  function hitTest(latLng) {
    if (!latLng) return null;
    const scale = Math.pow(2, map.getZoom());
    const px = worldX(latLng.lng()) * scale, py = worldY(latLng.lat()) * scale;
    const slop = coarsePointer() ? 8 : 3;
    for (let i = dots.length - 1; i >= 0; i--) {
      const dot = dots[i];
      const reach = dot.r + dot.strokeWidth / 2 + slop;
      const dx = dot.x * scale - px, dy = dot.y * scale - py;
      if (dx * dx + dy * dy <= reach * reach) return { kind: "dot", data: dot.data };
    }
    const wx = px / scale, wy = py / scale;
    for (let i = rects.length - 1; i >= 0; i--) {
      const rect = rects[i];
      if (wx >= rect.x0 && wx <= rect.x1 && wy >= rect.y0 && wy <= rect.y1) return { kind: "rect", data: rect.data };
    }
    return null;
  }

  const listeners = [
    map.addListener("bounds_changed", checkCoverage),
    map.addListener("idle", checkCoverage),
    map.addListener("click", (event) => {
      const hit = hitTest(event.latLng);
      if (hit && onClick) onClick(hit, event);
    }),
  ];
  if (!coarsePointer()) {
    listeners.push(map.addListener("mousemove", (event) => {
      const over = hitTest(event.latLng) !== null;
      if (over !== hovering) { hovering = over; map.setOptions({ draggableCursor: over ? "pointer" : null }); }
    }));
  }

  overlay.setMap(map);

  return {
    hitTest,
    setDots(items) {
      dots = items.map((item) => ({
        strokeWidth: 0, strokeAlpha: 1, alpha: 1, z: 0, ...item, x: worldX(item.lng), y: worldY(item.lat),
      })).sort((a, b) => a.z - b.z);
      schedule();
    },
    setRects(items) {
      rects = items.map((item) => ({
        strokeWidth: 0, alpha: 1, ...item,
        x0: worldX(item.west), x1: worldX(item.east), y0: worldY(item.north), y1: worldY(item.south),
      }));
      schedule();
    },
    destroy() {
      cancelAnimationFrame(frame);
      listeners.forEach((listener) => listener.remove());
      if (hovering) map.setOptions({ draggableCursor: null });
      overlay.setMap(null);
    },
  };
}
