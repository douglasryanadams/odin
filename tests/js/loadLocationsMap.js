import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const SOURCE_PATH = join(
  dirname(fileURLToPath(import.meta.url)),
  "../../static/js/locationsmap.js",
);

// locationsmap.js is a classic (non-module) script, like profile.js. Run it
// in its own vm context with just the DOM globals it needs.
export function loadLocationsMap() {
  const sandbox = { document, window, console };
  vm.createContext(sandbox);
  vm.runInContext(readFileSync(SOURCE_PATH, "utf8"), sandbox);
  return sandbox;
}
