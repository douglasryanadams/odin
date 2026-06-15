import { describe, expect, test } from "vitest";
import { loadLocationsMap } from "./loadLocationsMap.js";

const lm = loadLocationsMap();

describe("projectPoint", () => {
  test("equirectangular projection flips latitude into SVG y (north up)", () => {
    // London: positive latitude -> negative y (toward the top of the viewBox).
    expect(lm.projectPoint(51.5074, -0.1278)).toEqual({ x: -0.1278, y: -51.5074 });
  });

  test("negative latitude / positive longitude (Sydney)", () => {
    expect(lm.projectPoint(-33.87, 151.21)).toEqual({ x: 151.21, y: 33.87 });
  });
});

describe("computeBounds", () => {
  test("a single point has zero-width/height bounds", () => {
    expect(lm.computeBounds([{ x: 10, y: 20 }])).toEqual({
      minX: 10, minY: 20, maxX: 10, maxY: 20,
    });
  });

  test("spans the min/max of all points", () => {
    const points = [{ x: 2.35, y: -48.85 }, { x: 21.01, y: -52.23 }];
    expect(lm.computeBounds(points)).toEqual({
      minX: 2.35, minY: -52.23, maxX: 21.01, maxY: -48.85,
    });
  });
});

describe("fitViewBox", () => {
  test("expands a single point to the minimum span, padded centered", () => {
    const box = lm.fitViewBox({ minX: 10, minY: 20, maxX: 10, maxY: 20 });
    expect(box).toEqual({ minX: 8, minY: 18, width: 4, height: 4 });
  });

  test("pads a box already larger than the minimum span", () => {
    const box = lm.fitViewBox({ minX: 0, minY: 0, maxX: 10, maxY: 5 });
    expect(box).toEqual({ minX: -2, minY: -1, width: 14, height: 7 });
  });

  test("clamps width to the world maximum near the poles", () => {
    const box = lm.fitViewBox({ minX: -170, minY: 80, maxX: 170, maxY: 85 });
    expect(box.width).toBe(360);
    expect(box.minX).toBe(-180);
    expect(box.height).toBeCloseTo(7);
    expect(box.minY).toBeCloseTo(79);
  });

  test("shifts the box back inside world bounds near the antimeridian", () => {
    const box = lm.fitViewBox({ minX: 170, minY: -5, maxX: 179, maxY: 5 });
    expect(box.width).toBeCloseTo(12.6);
    expect(box.minX).toBeCloseTo(167.4);
    expect(box.minX + box.width).toBeCloseTo(180);
  });
});

describe("clampToWorld", () => {
  test("leaves a box that's already inside world bounds unchanged", () => {
    const box = lm.clampToWorld({ minX: -2, minY: -1, width: 14, height: 7 });
    expect(box).toEqual({ minX: -2, minY: -1, width: 14, height: 7 });
  });

  test("shifts a box back inside world bounds near the antimeridian", () => {
    const box = lm.clampToWorld({ minX: 168.2, minY: -7, width: 12.6, height: 14 });
    expect(box.width).toBeCloseTo(12.6);
    expect(box.minX).toBeCloseTo(167.4);
    expect(box.minX + box.width).toBeCloseTo(180);
  });

  test("shifts a box back inside world bounds near the poles", () => {
    const box = lm.clampToWorld({ minX: -10, minY: 86, width: 20, height: 10 });
    expect(box).toEqual({ minX: -10, minY: 80, width: 20, height: 10 });
  });
});

describe("zoomViewBox", () => {
  const limits = { minWidth: 1, maxWidth: 360 };

  test("zooming in (factor > 1) shrinks the span around the same center", () => {
    const viewBox = { minX: -10, minY: -5, width: 20, height: 10 };
    const box = lm.zoomViewBox(viewBox, 2, limits);
    expect(box).toEqual({ minX: -5, minY: -2.5, width: 10, height: 5 });
  });

  test("zooming out (factor < 1) grows the span around the same center", () => {
    const viewBox = { minX: -5, minY: -2.5, width: 10, height: 5 };
    const box = lm.zoomViewBox(viewBox, 0.5, limits);
    expect(box).toEqual({ minX: -10, minY: -5, width: 20, height: 10 });
  });

  test("clamps zooming in past minWidth", () => {
    const viewBox = { minX: -2, minY: -1, width: 4, height: 2 };
    const box = lm.zoomViewBox(viewBox, 100, limits);
    expect(box.width).toBe(1);
    expect(box.height).toBe(0.5);
  });

  test("clamps zooming out past maxWidth", () => {
    const viewBox = { minX: -180, minY: -45, width: 360, height: 90 };
    const box = lm.zoomViewBox(viewBox, 0.5, limits);
    expect(box.width).toBe(360);
    expect(box.minX).toBe(-180);
  });
});

describe("panViewBox", () => {
  test("shifts the viewBox by the given delta", () => {
    const viewBox = { minX: 0, minY: 0, width: 10, height: 5 };
    const box = lm.panViewBox(viewBox, 3, -2);
    expect(box).toEqual({ minX: 3, minY: -2, width: 10, height: 5 });
  });

  test("clamps panning past the world edge", () => {
    const viewBox = { minX: -170, minY: 0, width: 20, height: 10 };
    const box = lm.panViewBox(viewBox, -20, 0);
    expect(box.minX).toBe(-180);
    expect(box.width).toBe(20);
  });
});

describe("clusterPoints", () => {
  test("merges points within the threshold into one cluster", () => {
    const points = [{ x: 0, y: 0 }, { x: 0.1, y: 0.1 }];
    const clusters = lm.clusterPoints(points, 1);
    expect(clusters).toHaveLength(1);
    expect(clusters[0].indices).toEqual([0, 1]);
    expect(clusters[0].x).toBeCloseTo(0.05);
    expect(clusters[0].y).toBeCloseTo(0.05);
  });

  test("keeps distant points in separate clusters", () => {
    const points = [{ x: 0, y: 0 }, { x: 10, y: 10 }];
    const clusters = lm.clusterPoints(points, 1);
    expect(clusters).toHaveLength(2);
    expect(clusters[0].indices).toEqual([0]);
    expect(clusters[1].indices).toEqual([1]);
  });

  test("recomputes the cluster centroid as points join", () => {
    const points = [{ x: 0, y: 0 }, { x: 0.5, y: 0 }, { x: 10, y: 10 }];
    const clusters = lm.clusterPoints(points, 1);
    expect(clusters).toHaveLength(2);
    expect(clusters[0].indices).toEqual([0, 1]);
    expect(clusters[0].x).toBeCloseTo(0.25);
    expect(clusters[0].y).toBeCloseTo(0);
    expect(clusters[1].indices).toEqual([2]);
  });
});

describe("sweepDelay", () => {
  test("the viewBox's left edge sweeps first", () => {
    expect(lm.sweepDelay(0, { minX: 0, width: 10 }, 3)).toBe(0);
  });

  test("the viewBox's right edge sweeps last, at the full period", () => {
    expect(lm.sweepDelay(10, { minX: 0, width: 10 }, 3)).toBe(3);
  });

  test("the midpoint sweeps halfway through the period", () => {
    expect(lm.sweepDelay(5, { minX: 0, width: 10 }, 3)).toBe(1.5);
  });
});

describe("computeVisibleLabels", () => {
  test("keeps both labels visible when their intervals don't overlap", () => {
    const candidates = [{ cx: 0, width: 2 }, { cx: 10, width: 2 }];
    expect(lm.computeVisibleLabels(candidates)).toEqual([0, 1]);
  });

  test("hides the eastern label when two labels overlap", () => {
    const candidates = [{ cx: 0, width: 4 }, { cx: 2, width: 4 }];
    expect(lm.computeVisibleLabels(candidates)).toEqual([0]);
  });

  test("keeps a later non-overlapping label even after an earlier one was hidden", () => {
    const candidates = [{ cx: 0, width: 2 }, { cx: 1, width: 2 }, { cx: 10, width: 2 }];
    expect(lm.computeVisibleLabels(candidates)).toEqual([0, 2]);
  });

  test("returns original indices regardless of input order", () => {
    const candidates = [{ cx: 10, width: 2 }, { cx: 0, width: 4 }, { cx: 1, width: 4 }];
    expect(lm.computeVisibleLabels(candidates)).toEqual([0, 1]);
  });
});

describe("sweepArcPath", () => {
  test("returns a vertical bowed arc spanning 50% past the viewBox's top and bottom edges", () => {
    const viewBox = { minX: 0, minY: 0, width: 10, height: 10 };
    expect(lm.sweepArcPath(viewBox)).toBe("M0,-5 Q0.8,5 0,15");
  });
});

describe("geoJsonToPaths", () => {
  test("builds one path per LineString", () => {
    const geojson = {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          properties: {},
          geometry: { type: "LineString", coordinates: [[0, 0], [10, 20], [-5, -15]] },
        },
      ],
    };
    expect(lm.geoJsonToPaths(geojson)).toEqual(["M0,0 L10,-20 L-5,15"]);
  });

  test("expands a MultiLineString into one path per line", () => {
    const geojson = {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          properties: {},
          geometry: {
            type: "MultiLineString",
            coordinates: [[[1, 1], [2, 2]], [[3, 3], [4, 4]]],
          },
        },
      ],
    };
    expect(lm.geoJsonToPaths(geojson)).toEqual(["M1,-1 L2,-2", "M3,-3 L4,-4"]);
  });
});

describe("renderLocationsMap", () => {
  const geojson = {
    type: "FeatureCollection",
    features: [
      { type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: [[0, 0], [10, 10]] } },
      { type: "Feature", properties: { kind: "border" }, geometry: { type: "LineString", coordinates: [[1, 1], [2, 2]] } },
    ],
  };

  function buildContainer() {
    document.body.innerHTML = '<div id="locations-map"></div>';
    return document.getElementById("locations-map");
  }

  test("renders nothing for an empty locations list", () => {
    const container = buildContainer();
    lm.renderLocationsMap(container, [], geojson);
    expect(container.children.length).toBe(0);
  });

  test("renders an animated sweep arc behind the pins", () => {
    const container = buildContainer();
    const locations = [
      { name: "Warsaw, Poland", latitude: 52.23, longitude: 21.01, caption: "Birthplace" },
    ];
    lm.renderLocationsMap(container, locations, geojson);

    const svg = container.querySelector("svg.locations-map__svg");
    const sweeps = svg.querySelectorAll(".locations-map__sweep");
    expect(sweeps).toHaveLength(1);
    expect(sweeps[0].getAttribute("d")).not.toBe("");

    const children = Array.from(svg.children);
    const sweepIndex = children.indexOf(sweeps[0]);
    const pinIndex = children.findIndex((el) => el.classList.contains("locations-map__pin"));
    expect(sweepIndex).toBeLessThan(pinIndex);
  });

  test("renders a basemap path, a pin per location, and an accessible list", () => {
    const container = buildContainer();
    const locations = [
      { name: "Warsaw, Poland", latitude: 52.23, longitude: 21.01, caption: "Birthplace" },
      { name: "Paris, France", latitude: 48.85, longitude: 2.35, caption: "Lived and worked" },
    ];
    lm.renderLocationsMap(container, locations, geojson);

    const svg = container.querySelector("svg.locations-map__svg");
    expect(svg).not.toBeNull();
    expect(svg.getAttribute("role")).toBe("img");
    expect(svg.getAttribute("aria-label")).toContain("2");
    expect(svg.querySelectorAll(".locations-map__land")).toHaveLength(1);
    expect(svg.querySelectorAll(".locations-map__border")).toHaveLength(1);
    expect(svg.querySelectorAll(".locations-map__pin")).toHaveLength(2);

    const items = container.querySelectorAll(".locations-map__list .locations-map__list-item");
    expect(items).toHaveLength(2);
    expect(items[0].querySelector(".locations-map__list-name").textContent).toBe("Warsaw, Poland");
    expect(items[0].querySelector(".locations-map__list-caption").textContent).toBe("Birthplace");
  });

  test("sets a --pin-r custom property on the svg root for the CSS pin glow", () => {
    const container = buildContainer();
    const locations = [
      { name: "Warsaw, Poland", latitude: 52.23, longitude: 21.01, caption: "Birthplace" },
    ];
    lm.renderLocationsMap(container, locations, geojson);

    const svg = container.querySelector("svg.locations-map__svg");
    const pinR = Number(svg.style.getPropertyValue("--pin-r"));
    expect(pinR).toBeGreaterThan(0);
    expect(svg.querySelector(".locations-map__pin").getAttribute("r")).toBe(String(pinR));
  });

  test("flips label position and anchor for pins in the right half of the viewBox", () => {
    const container = buildContainer();
    const locations = [
      { name: "Warsaw, Poland", latitude: 52.23, longitude: 21.01, caption: "Birthplace" },
      { name: "Paris, France", latitude: 48.85, longitude: 2.35, caption: "Lived and worked" },
    ];
    lm.renderLocationsMap(container, locations, geojson);

    const svg = container.querySelector("svg.locations-map__svg");
    const labels = svg.querySelectorAll(".locations-map__pin-label");
    expect(labels).toHaveLength(2);

    // Warsaw sits in the right half of the viewBox: its label extends left of the pin.
    expect(labels[0].textContent).toBe("[1]");
    expect(labels[0].getAttribute("text-anchor")).toBe("end");
    expect(Number(labels[0].getAttribute("x"))).toBeLessThan(21.01);

    // Paris sits in the left half: its label keeps extending right of the pin.
    expect(labels[1].textContent).toBe("[2]");
    expect(labels[1].getAttribute("text-anchor")).toBe("start");
    expect(Number(labels[1].getAttribute("x"))).toBeGreaterThan(2.35);
  });

  test("staggers each pin's sweep animation delay left to right", () => {
    const container = buildContainer();
    const locations = [
      { name: "Warsaw, Poland", latitude: 52.23, longitude: 21.01, caption: "Birthplace" },
      { name: "Paris, France", latitude: 48.85, longitude: 2.35, caption: "Lived and worked" },
    ];
    lm.renderLocationsMap(container, locations, geojson);

    const svg = container.querySelector("svg.locations-map__svg");
    const pins = svg.querySelectorAll(".locations-map__pin");

    // Paris (further west) sweeps before Warsaw (further east). Negative
    // delays start each pin's animation already partway through its cycle,
    // so the blip lands in sync with the sweep line on the first pass too.
    const parisDelay = parseFloat(pins[1].style.animationDelay);
    const warsawDelay = parseFloat(pins[0].style.animationDelay);
    expect(parisDelay).toBeLessThanOrEqual(0);
    expect(warsawDelay).toBeLessThanOrEqual(0);
    expect(parisDelay).toBeLessThanOrEqual(warsawDelay);
  });

  test("resyncs each pin's sweep delay to the live viewBox after zooming", () => {
    const container = buildContainer();
    const locations = [
      { name: "Warsaw, Poland", latitude: 52.23, longitude: 21.01, caption: "Birthplace" },
      { name: "Paris, France", latitude: 48.85, longitude: 2.35, caption: "Lived and worked" },
    ];
    lm.renderLocationsMap(container, locations, geojson);

    const svg = container.querySelector("svg.locations-map__svg");
    const pins = svg.querySelectorAll(".locations-map__pin");
    const cxs = Array.from(pins).map((pin) => Number(pin.getAttribute("cx")));

    container.querySelector('[data-zoom="in"]').click();

    const [minX, minY, width, height] = svg.getAttribute("viewBox").split(" ").map(Number);
    const newViewBox = { minX, minY, width, height };
    pins.forEach((pin, i) => {
      const expectedDelay = lm.sweepDelay(cxs[i], newViewBox, 3) - 3;
      expect(parseFloat(pin.style.animationDelay)).toBeCloseTo(expectedDelay);
    });
  });

  test("renders zoom and reset controls that update the svg viewBox", () => {
    const container = buildContainer();
    const locations = [
      { name: "Warsaw, Poland", latitude: 52.23, longitude: 21.01, caption: "Birthplace" },
      { name: "Paris, France", latitude: 48.85, longitude: 2.35, caption: "Lived and worked" },
    ];
    lm.renderLocationsMap(container, locations, geojson);

    const svg = container.querySelector("svg.locations-map__svg");
    const homeViewBox = svg.getAttribute("viewBox");

    const zoomIn = container.querySelector('[data-zoom="in"]');
    const zoomOut = container.querySelector('[data-zoom="out"]');
    const reset = container.querySelector('[data-zoom="reset"]');
    expect(zoomIn.getAttribute("aria-label")).toBe("Zoom in");
    expect(zoomOut.getAttribute("aria-label")).toBe("Zoom out");
    expect(reset.getAttribute("aria-label")).toBe("Reset map view");

    zoomIn.click();
    expect(svg.getAttribute("viewBox")).not.toBe(homeViewBox);

    reset.click();
    expect(svg.getAttribute("viewBox")).toBe(homeViewBox);
  });

  test("redraws the sweep arc to cover the live viewBox after zooming out", () => {
    const container = buildContainer();
    const locations = [
      { name: "Warsaw, Poland", latitude: 52.23, longitude: 21.01, caption: "Birthplace" },
    ];
    lm.renderLocationsMap(container, locations, geojson);

    const svg = container.querySelector("svg.locations-map__svg");
    const sweep = svg.querySelector(".locations-map__sweep");

    container.querySelector('[data-zoom="out"]').click();

    const [minX, minY, width, height] = svg.getAttribute("viewBox").split(" ").map(Number);
    expect(sweep.getAttribute("d")).toBe(lm.sweepArcPath({ minX, minY, width, height }));
  });

  test("keeps pin radius and label font size constant on screen when zooming", () => {
    const container = buildContainer();
    const locations = [
      { name: "Warsaw, Poland", latitude: 52.23, longitude: 21.01, caption: "Birthplace" },
      { name: "Paris, France", latitude: 48.85, longitude: 2.35, caption: "Lived and worked" },
    ];
    lm.renderLocationsMap(container, locations, geojson);

    const svg = container.querySelector("svg.locations-map__svg");
    const pin = svg.querySelector(".locations-map__pin");
    const label = svg.querySelector(".locations-map__pin-label");

    const homeWidth = parseFloat(svg.getAttribute("viewBox").split(" ")[2]);
    const homeRadius = Number(pin.getAttribute("r"));
    const homeFontSize = Number(label.getAttribute("font-size"));
    const homePinR = Number(svg.style.getPropertyValue("--pin-r"));

    container.querySelector('[data-zoom="in"]').click();

    const newWidth = parseFloat(svg.getAttribute("viewBox").split(" ")[2]);
    const scale = newWidth / homeWidth;

    expect(Number(pin.getAttribute("r"))).toBeCloseTo(homeRadius * scale);
    expect(Number(label.getAttribute("font-size"))).toBeCloseTo(homeFontSize * scale);
    expect(Number(svg.style.getPropertyValue("--pin-r"))).toBeCloseTo(homePinR * scale);
  });

  test("labels a clustered pin with the indices of all its locations", () => {
    const container = buildContainer();
    const locations = [
      { name: "Dallas, TX", latitude: 32.78, longitude: -96.80, caption: "Event A" },
      { name: "Dallas Suburb", latitude: 32.85, longitude: -96.85, caption: "Event B" },
    ];
    lm.renderLocationsMap(container, locations, geojson);

    const svg = container.querySelector("svg.locations-map__svg");
    const pins = svg.querySelectorAll(".locations-map__pin");
    expect(pins).toHaveLength(1);

    const labels = svg.querySelectorAll(".locations-map__pin-label");
    expect(labels).toHaveLength(1);
    expect(labels[0].textContent).toBe("[1,2]");

    // Both locations still get their own row in the accessible list.
    expect(container.querySelectorAll(".locations-map__list-item")).toHaveLength(2);
  });

  test("hides a colliding label at the home view and reveals it on zoom", () => {
    const container = buildContainer();
    // Linz and Graz are 0.1 degrees apart in longitude -- close enough that
    // their labels collide at the home view's minimum 4-degree span, but far
    // enough apart (with the latitude difference) to stay separate pins.
    const locations = [
      { name: "Linz", latitude: 50.0, longitude: 10.0, caption: "Event A" },
      { name: "Graz", latitude: 50.2, longitude: 10.1, caption: "Event B" },
    ];
    lm.renderLocationsMap(container, locations, geojson);

    const svg = container.querySelector("svg.locations-map__svg");
    expect(svg.querySelectorAll(".locations-map__pin")).toHaveLength(2);
    const labels = svg.querySelectorAll(".locations-map__pin-label");
    expect(labels[0].classList.contains("is-hidden")).toBe(false);
    expect(labels[1].classList.contains("is-hidden")).toBe(true);

    const zoomIn = container.querySelector('[data-zoom="in"]');
    for (let i = 0; i < 8; i += 1) zoomIn.click();

    expect(labels[0].classList.contains("is-hidden")).toBe(false);
    expect(labels[1].classList.contains("is-hidden")).toBe(false);
  });

  test("does not merge distant cities just because one location is far away", () => {
    const container = buildContainer();
    const locations = [
      { name: "New York City, New York", latitude: 40.7128, longitude: -74.0060, caption: "Event A" },
      { name: "Philadelphia, Pennsylvania", latitude: 39.9526, longitude: -75.1652, caption: "Event B" },
      { name: "Paris, France", latitude: 48.8566, longitude: 2.3522, caption: "Event C" },
    ];
    lm.renderLocationsMap(container, locations, geojson);

    const svg = container.querySelector("svg.locations-map__svg");
    expect(svg.querySelectorAll(".locations-map__pin")).toHaveLength(3);
  });
});
