import js from "@eslint/js";
import globals from "globals";

export default [
  js.configs.recommended,
  {
    files: ["static/js/**/*.js"],
    languageOptions: {
      ecmaVersion: 2024,
      sourceType: "script",
      globals: {
        ...globals.browser,
        ODIN_QUERY: "readonly",
      },
    },
    rules: {
      "no-unused-vars": "warn",
      "no-undef": "error",
    },
  },
  {
    // profile.js calls renderLocationsMap, which is defined as a top-level
    // function in locationsmap.js — both load as classic scripts into the
    // same global scope, so it's a runtime global from profile.js's view.
    files: ["static/js/profile.js"],
    languageOptions: {
      globals: {
        renderLocationsMap: "readonly",
      },
    },
  },
];
