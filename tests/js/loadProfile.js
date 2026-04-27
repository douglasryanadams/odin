import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const SOURCE_PATH = join(
  dirname(fileURLToPath(import.meta.url)),
  "../../src/odin/static/js/profile.js",
);

// happy-dom (vitest env) provides DOM globals on globalThis. We pass them
// into a vm context so profile.js's function declarations attach to the
// sandbox instead of polluting the test scope. If profile.js ever moves
// to ES modules, replace this harness with a direct dynamic import.
export function loadProfile() {
  const sandbox = {
    document,
    window,
    URL,
    EventSource: class {
      close() {}
    },
    console,
  };
  vm.createContext(sandbox);
  vm.runInContext(readFileSync(SOURCE_PATH, "utf8"), sandbox);
  return sandbox;
}
