import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const LOCATIONSMAP_SOURCE_PATH = join(
  dirname(fileURLToPath(import.meta.url)),
  "../../static/js/locationsmap.js",
);
const SOURCE_PATH = join(
  dirname(fileURLToPath(import.meta.url)),
  "../../static/js/profile.js",
);

// happy-dom (vitest env) provides DOM globals on globalThis. We pass them
// into a vm context so profile.js's function declarations attach to the
// sandbox instead of polluting the test scope. If profile.js ever moves
// to ES modules, replace this harness with a direct dynamic import.
//
// locationsmap.js is loaded into the same context first, mirroring the two
// <script defer> tags in profile.html sharing one global scope — this is how
// profile.js reaches renderLocationsMap.
export function loadProfile() {
  const sandbox = {
    document,
    window,
    URL,
    EventSource: class {
      close() {}
    },
    console,
    // The progress bar uses performance.now() + requestAnimationFrame for
    // the cursor-blink and inter-stage fill animation. Pass these through
    // from the happy-dom-provided globals (vitest env).
    performance,
    requestAnimationFrame:
      typeof requestAnimationFrame !== "undefined"
        ? requestAnimationFrame
        : (cb) => setTimeout(() => cb(performance.now()), 16),
    cancelAnimationFrame:
      typeof cancelAnimationFrame !== "undefined"
        ? cancelAnimationFrame
        : (id) => clearTimeout(id),
    setTimeout,
    clearTimeout,
    // The locations section lazy-fetches the vendored basemap. Tests that
    // don't care about its contents get an empty FeatureCollection.
    fetch: () => Promise.resolve({
      json: () => Promise.resolve({ type: "FeatureCollection", features: [] }),
    }),
  };
  vm.createContext(sandbox);
  vm.runInContext(readFileSync(LOCATIONSMAP_SOURCE_PATH, "utf8"), sandbox);
  vm.runInContext(readFileSync(SOURCE_PATH, "utf8"), sandbox);
  return sandbox;
}
