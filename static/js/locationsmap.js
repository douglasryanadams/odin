// Odin locations map — pure projection/layout helpers plus an inline SVG
// renderer for a profile's `locations` (see static/maps/basemap.geojson).
//
// Equirectangular projection: x = longitude, y = -latitude. With SVG's
// y-down coordinate system this puts north at the top without any further
// transform. Coordinates are degrees throughout, so a viewBox can be set
// directly from a fitted bounding box.
//
// Basemap features carry `properties.kind === "border"` for country
// boundary lines; everything else is treated as coastline.

const SVG_NS = "http://www.w3.org/2000/svg";

// Pad the pins' bounding box by 20% on each axis before fitting the viewBox.
const LOCATIONSMAP_PADDING = 0.2;
// Minimum viewBox span in degrees — roughly the scale of a US state, per the
// product call to never zoom in tighter than that even for a single pin.
const LOCATIONSMAP_MIN_SPAN = 4;
// Pins within this fraction of the viewBox's larger span are merged into one
// marker (e.g. several Dallas-area events collapse to a single pin).
const LOCATIONSMAP_CLUSTER_FRACTION = 0.04;
// Regardless of the fraction above, never cluster across a gap wider than
// this many degrees (~30km / "same metro area") -- keeps one far-flung
// location from inflating the merge radius for everything else.
const LOCATIONSMAP_CLUSTER_MAX_DISTANCE = 0.3;
// Pin radius and label size, as a fraction of the viewBox's larger span.
const LOCATIONSMAP_PIN_RADIUS_FRACTION = 0.006;
const LOCATIONSMAP_LABEL_FONT_FRACTION = 0.016;
// Approximate monospace glyph width as a fraction of font-size, used to
// estimate each label's on-screen footprint for collision detection.
const LOCATIONSMAP_LABEL_GLYPH_WIDTH_FRACTION = 0.6;
// Pins blink in sequence, west to east, over this many seconds before looping.
const LOCATIONSMAP_SWEEP_PERIOD_S = 3;
// Each zoom-button click scales the viewBox span by this factor.
const LOCATIONSMAP_ZOOM_FACTOR = 1.4;
// Zooming in is capped at 1/8 of the initial (fitted) viewBox span.
const LOCATIONSMAP_MAX_ZOOM = 8;

function projectPoint(latitude, longitude) {
  return { x: longitude, y: -latitude };
}

function computeBounds(points) {
  return {
    minX: Math.min(...points.map((p) => p.x)),
    minY: Math.min(...points.map((p) => p.y)),
    maxX: Math.max(...points.map((p) => p.x)),
    maxY: Math.max(...points.map((p) => p.y)),
  };
}

// Shift a viewBox back inside world bounds (±180° longitude, ±90° latitude)
// if it extends past an edge, preserving its width and height.
function clampToWorld({ minX, minY, width, height }) {
  let maxX = minX + width;
  let maxY = minY + height;

  if (minX < -180) { maxX += -180 - minX; minX = -180; }
  if (maxX > 180) { minX -= maxX - 180; maxX = 180; }
  if (minY < -90) { maxY += -90 - minY; minY = -90; }
  if (maxY > 90) { minY -= maxY - 90; maxY = 90; }

  return { minX, minY, width: maxX - minX, height: maxY - minY };
}

// Pad a bounding box, clamp its span to a minimum (and to the whole world),
// and shift it back inside world bounds if padding pushed it over an edge.
function fitViewBox(bounds, { padding = LOCATIONSMAP_PADDING, minSpan = LOCATIONSMAP_MIN_SPAN } = {}) {
  const cx = (bounds.minX + bounds.maxX) / 2;
  const cy = (bounds.minY + bounds.maxY) / 2;

  let width = (bounds.maxX - bounds.minX) * (1 + 2 * padding);
  let height = (bounds.maxY - bounds.minY) * (1 + 2 * padding);
  width = Math.min(Math.max(width, minSpan), 360);
  height = Math.min(Math.max(height, minSpan), 180);

  return clampToWorld({ minX: cx - width / 2, minY: cy - height / 2, width, height });
}

// Zoom toward (factor > 1) or away from (factor < 1) the current center,
// preserving aspect ratio and clamping the span to [minWidth, maxWidth].
function zoomViewBox(viewBox, factor, { minWidth, maxWidth }) {
  const cx = viewBox.minX + viewBox.width / 2;
  const cy = viewBox.minY + viewBox.height / 2;
  const aspect = viewBox.height / viewBox.width;
  const width = Math.min(Math.max(viewBox.width / factor, minWidth), maxWidth);
  const height = width * aspect;
  return clampToWorld({ minX: cx - width / 2, minY: cy - height / 2, width, height });
}

// Shift a viewBox by (dx, dy) viewBox units, clamped to world bounds.
function panViewBox(viewBox, dx, dy) {
  return clampToWorld({
    minX: viewBox.minX + dx,
    minY: viewBox.minY + dy,
    width: viewBox.width,
    height: viewBox.height,
  });
}

// Greedy single-pass clustering: a point joins the nearest existing cluster
// if its centroid is within `threshold`, otherwise it starts a new one. The
// centroid is recomputed as the running average of its members.
function clusterPoints(points, threshold) {
  const clusters = [];
  points.forEach((point, index) => {
    const cluster = clusters.find((c) => Math.hypot(c.x - point.x, c.y - point.y) <= threshold);
    if (cluster) {
      const n = cluster.indices.length;
      cluster.x = (cluster.x * n + point.x) / (n + 1);
      cluster.y = (cluster.y * n + point.y) / (n + 1);
      cluster.indices.push(index);
    } else {
      clusters.push({ x: point.x, y: point.y, indices: [index] });
    }
  });
  return clusters;
}

// Given candidates {cx, width} in viewBox units, return the original indices
// (ascending) whose labels can be shown without overlapping a label to their
// west. Processes west to east, keeping a label only if its left edge clears
// the right edge of the last kept label -- the same greedy idea as
// clusterPoints, but packing 1D label-width intervals instead of merging 2D
// points.
function computeVisibleLabels(candidates) {
  const visible = [];
  const order = candidates.map((_, index) => index).sort((a, b) => candidates[a].cx - candidates[b].cx);
  let lastRightEdge = -Infinity;
  order.forEach((index) => {
    const { cx, width } = candidates[index];
    const leftEdge = cx - width / 2;
    if (leftEdge >= lastRightEdge) {
      visible.push(index);
      lastRightEdge = cx + width / 2;
    }
  });
  return visible.sort((a, b) => a - b);
}

// A pin's delay into the sweep animation, proportional to how far east it
// sits within the viewBox (0 at the west edge, `period` at the east edge).
function sweepDelay(x, viewBox, period) {
  return ((x - viewBox.minX) / viewBox.width) * period;
}

// SVG path `d` for the animated sweep arc: a vertical line at the viewBox's
// left edge, bowed outward at its midpoint, extended 50% past the top and
// bottom edges so it still covers the visible area after zooming out.
function sweepArcPath(viewBox) {
  const x = viewBox.minX;
  const y0 = viewBox.minY - viewBox.height * 0.5;
  const y1 = viewBox.minY + viewBox.height * 1.5;
  const bow = viewBox.height * 0.08;
  const ymid = (y0 + y1) / 2;
  return `M${x},${y0} Q${x + bow},${ymid} ${x},${y1}`;
}

function lineToPath(line) {
  return line
    .map(([lon, lat], i) => {
      const { x, y } = projectPoint(lat, lon);
      return `${i === 0 ? "M" : "L"}${x},${y}`;
    })
    .join(" ");
}

function geoJsonToPaths(geojson) {
  const paths = [];
  (geojson.features || []).forEach((feature) => {
    const geom = feature.geometry;
    if (!geom) return;
    if (geom.type === "LineString") {
      paths.push(lineToPath(geom.coordinates));
    } else if (geom.type === "MultiLineString") {
      geom.coordinates.forEach((line) => paths.push(lineToPath(line)));
    }
  });
  return paths;
}

function _el(tag, className, content) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content !== undefined) node.textContent = content;
  return node;
}

function _svgEl(tag, attrs) {
  const node = document.createElementNS(SVG_NS, tag);
  Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
  return node;
}

function _isBorder(feature) {
  return (feature.properties || {}).kind === "border";
}

function viewBoxString(viewBox) {
  return `${viewBox.minX} ${viewBox.minY} ${viewBox.width} ${viewBox.height}`;
}

function _zoomButton(label, ariaLabel, zoom) {
  const button = _el("button", "locations-map__zoom", label);
  button.type = "button";
  button.dataset.zoom = zoom;
  button.setAttribute("aria-label", ariaLabel);
  return button;
}

// Render the basemap + pins as an inline SVG, plus a parallel <ol> of place
// names and captions for accessibility and no-JS. Replaces `container`'s
// content; leaves it empty when there are no locations. The eslint disable
// below silences "unused" — profile.js calls this as a cross-script global
// (see config/eslint.config.js) and tests/js/loadLocationsMap.js exercises it
// directly.
// eslint-disable-next-line no-unused-vars
function renderLocationsMap(container, locations, geojson) {
  container.replaceChildren();
  if (!locations || !locations.length) return;

  const points = locations.map((loc) => projectPoint(loc.latitude, loc.longitude));
  const homeViewBox = fitViewBox(computeBounds(points));
  const maxSpan = Math.max(homeViewBox.width, homeViewBox.height);
  const clusterThreshold = Math.min(maxSpan * LOCATIONSMAP_CLUSTER_FRACTION, LOCATIONSMAP_CLUSTER_MAX_DISTANCE);
  const clusters = clusterPoints(points, clusterThreshold);

  const svg = _svgEl("svg", {
    class: "locations-map__svg",
    viewBox: viewBoxString(homeViewBox),
    role: "img",
    "aria-label": `Map of ${locations.length} key location${locations.length === 1 ? "" : "s"}`,
  });

  const land = { type: "FeatureCollection", features: (geojson.features || []).filter((f) => !_isBorder(f)) };
  const borders = { type: "FeatureCollection", features: (geojson.features || []).filter(_isBorder) };
  geoJsonToPaths(land).forEach((d) => {
    svg.appendChild(_svgEl("path", { class: "locations-map__land", d, "vector-effect": "non-scaling-stroke" }));
  });
  geoJsonToPaths(borders).forEach((d) => {
    svg.appendChild(_svgEl("path", { class: "locations-map__border", d, "vector-effect": "non-scaling-stroke" }));
  });

  const sweepPath = _svgEl("path", {
    class: "locations-map__sweep", d: sweepArcPath(homeViewBox), "vector-effect": "non-scaling-stroke",
  });
  svg.appendChild(sweepPath);

  const radius = maxSpan * LOCATIONSMAP_PIN_RADIUS_FRACTION;
  const fontSize = maxSpan * LOCATIONSMAP_LABEL_FONT_FRACTION;
  const midX = homeViewBox.minX + homeViewBox.width / 2;
  // One entry per cluster, revisited by syncPinsToViewBox() on every viewBox
  // change so pins and labels keep a constant on-screen size and each pin's
  // sweep delay stays matched to the sweep line at any zoom level.
  const pinEntries = [];
  clusters.forEach((cluster) => {
    const pin = _svgEl("circle", {
      class: "locations-map__pin", cx: cluster.x, cy: cluster.y, r: radius,
    });
    svg.appendChild(pin);
    // Pin labels are bracketed 1-based indices into `locations` (e.g. "[4]"
    // or "[4,5]" for a cluster), matching the numbering on the accessible
    // list below the map -- full place names rarely fit on screen for
    // geographically spread-out profiles, so the map points to the list.
    const labelText = `[${cluster.indices.map((index) => index + 1).join(",")}]`;
    // Pins past the viewBox midpoint get their label flipped to the left so
    // it doesn't run off the right edge of the map.
    const onRight = cluster.x > midX;
    const label = _svgEl("text", {
      class: "locations-map__pin-label",
      x: onRight ? cluster.x - radius * 1.5 : cluster.x + radius * 1.5,
      y: cluster.y,
      "font-size": fontSize,
      "text-anchor": onRight ? "end" : "start",
    });
    label.textContent = labelText;
    svg.appendChild(label);
    pinEntries.push({ pin, label, cx: cluster.x, onRight, labelLength: labelText.length });
  });

  const map = _el("div", "locations-map__map");
  map.appendChild(svg);

  const zoomInBtn = _zoomButton("+", "Zoom in", "in");
  const zoomOutBtn = _zoomButton("−", "Zoom out", "out");
  const resetBtn = _zoomButton("Reset", "Reset map view", "reset");
  const controls = _el("div", "locations-map__controls");
  controls.append(zoomInBtn, zoomOutBtn, resetBtn);
  map.appendChild(controls);

  container.appendChild(map);

  // Zoom and pan: currentViewBox tracks the live view, homeViewBox is the
  // fitted view restored by the reset button. Zooming in is capped at
  // homeViewBox's span / LOCATIONSMAP_MAX_ZOOM; zooming out is capped by
  // clampToWorld plus a max width that keeps the height within ±90°.
  const aspect = homeViewBox.height / homeViewBox.width;
  const zoomLimits = {
    minWidth: homeViewBox.width / LOCATIONSMAP_MAX_ZOOM,
    maxWidth: Math.min(360, 180 / aspect),
  };
  let currentViewBox = homeViewBox;

  // Pins and labels are sized in viewBox units, so zooming in (a smaller
  // viewBox) would otherwise make them cover more screen pixels. Rescale by
  // how much the viewBox has shrunk or grown relative to homeViewBox so they
  // keep a constant on-screen size, update the --pin-r custom property the
  // CSS glow reads from, and recompute each pin's sweep delay against the
  // current viewBox -- the sweep line's `d` and travel distance are also
  // relative to currentViewBox, so a pin's delay must track it too for the
  // blip to land when the line passes over that pin.
  const syncPinsToViewBox = () => {
    const scale = currentViewBox.width / homeViewBox.width;
    const scaledRadius = radius * scale;
    svg.style.setProperty("--pin-r", `${scaledRadius}`);
    pinEntries.forEach(({ pin, label, cx, onRight }) => {
      pin.setAttribute("r", scaledRadius);
      // Negative delay: the animation starts already partway through its
      // cycle, so the bright (0%) keyframe lands exactly when the sweep
      // line's translateX reaches this pin's x, on every loop including
      // the first.
      pin.style.animationDelay = `${sweepDelay(cx, currentViewBox, LOCATIONSMAP_SWEEP_PERIOD_S) - LOCATIONSMAP_SWEEP_PERIOD_S}s`;
      label.setAttribute("font-size", fontSize * scale);
      label.setAttribute("x", onRight ? cx - scaledRadius * 1.5 : cx + scaledRadius * 1.5);
    });

    // Hide labels that would collide on screen at the current zoom, west to
    // east, so the nearest-to-home label in a cluster of overlapping names
    // wins. Pins themselves stay visible; only labels toggle.
    const candidates = pinEntries.map(({ cx, labelLength }) => ({
      cx,
      width: labelLength * fontSize * scale * LOCATIONSMAP_LABEL_GLYPH_WIDTH_FRACTION,
    }));
    const visibleLabels = computeVisibleLabels(candidates);
    pinEntries.forEach(({ label }, index) => {
      label.classList.toggle("is-hidden", !visibleLabels.includes(index));
    });
  };

  const setViewBox = (viewBox) => {
    currentViewBox = viewBox;
    svg.setAttribute("viewBox", viewBoxString(currentViewBox));
    sweepPath.setAttribute("d", sweepArcPath(currentViewBox));
    syncPinsToViewBox();
  };
  syncPinsToViewBox();

  zoomInBtn.addEventListener("click", () => {
    setViewBox(zoomViewBox(currentViewBox, LOCATIONSMAP_ZOOM_FACTOR, zoomLimits));
  });
  zoomOutBtn.addEventListener("click", () => {
    setViewBox(zoomViewBox(currentViewBox, 1 / LOCATIONSMAP_ZOOM_FACTOR, zoomLimits));
  });
  resetBtn.addEventListener("click", () => {
    setViewBox(homeViewBox);
  });

  // Drag-to-pan: pointer deltas are measured in screen pixels and converted
  // to viewBox units via the SVG's rendered size, so panning speed tracks
  // the current zoom level.
  let dragStart = null;
  svg.addEventListener("pointerdown", (event) => {
    dragStart = { x: event.clientX, y: event.clientY, viewBox: currentViewBox };
    svg.setPointerCapture(event.pointerId);
    svg.classList.add("is-dragging");
  });
  svg.addEventListener("pointermove", (event) => {
    if (!dragStart) return;
    const rect = svg.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const dx = ((event.clientX - dragStart.x) / rect.width) * dragStart.viewBox.width;
    const dy = ((event.clientY - dragStart.y) / rect.height) * dragStart.viewBox.height;
    setViewBox(panViewBox(dragStart.viewBox, -dx, -dy));
  });
  const endDrag = (event) => {
    if (!dragStart) return;
    dragStart = null;
    svg.classList.remove("is-dragging");
    svg.releasePointerCapture(event.pointerId);
  };
  svg.addEventListener("pointerup", endDrag);
  svg.addEventListener("pointercancel", endDrag);

  const list = _el("ol", "locations-map__list");
  locations.forEach((loc) => {
    const item = _el("li", "locations-map__list-item");
    item.appendChild(_el("span", "locations-map__list-name", loc.name));
    item.appendChild(_el("span", "locations-map__list-caption", loc.caption));
    list.appendChild(item);
  });
  container.appendChild(list);
}
