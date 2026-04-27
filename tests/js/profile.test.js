import { beforeEach, describe, expect, test } from "vitest";
import { loadProfile } from "./loadProfile.js";

const profile = loadProfile();

describe("el", () => {
  test("creates element with className and content", () => {
    expect(profile.el("li", "foo", "bar").outerHTML).toBe('<li class="foo">bar</li>');
  });

  test("omits className when not provided", () => {
    expect(profile.el("div").className).toBe("");
  });

  test("leaves textContent empty when content is undefined", () => {
    expect(profile.el("span", "x").textContent).toBe("");
  });
});

describe("buildGauge", () => {
  test("renders label, percent value, and fill width", () => {
    const wrap = profile.buildGauge("Conf", 78, "gauge--confidence");
    expect(wrap.querySelector(".gauge__label").textContent).toBe("Conf");
    expect(wrap.querySelector(".gauge__value").textContent).toBe("78%");
    expect(wrap.querySelector(".gauge__fill").style.width).toBe("78%");
    expect(wrap.className).toBe("gauge gauge--confidence");
  });
});

describe("buildSentimentGauge", () => {
  test("positive position prefixes value with +", () => {
    const wrap = profile.buildSentimentGauge("S", 0.32);
    expect(wrap.querySelector(".gauge__value").textContent).toBe("+32");
    expect(wrap.querySelector(".gauge__marker").style.left).toBe("66%");
  });

  test("negative position keeps native sign", () => {
    const wrap = profile.buildSentimentGauge("S", -0.5);
    expect(wrap.querySelector(".gauge__value").textContent).toBe("-50");
    expect(wrap.querySelector(".gauge__marker").style.left).toBe("25%");
  });

  test("zero falls into else branch with no sign prefix", () => {
    const wrap = profile.buildSentimentGauge("S", 0);
    expect(wrap.querySelector(".gauge__value").textContent).toBe("0");
  });
});

describe("setCategory", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <span class="badge badge--category" id="category-badge">
        <i class="fa-solid fa-circle-nodes" aria-hidden="true"></i>
        <span class="badge__label">Pending…</span>
      </span>
    `;
  });

  test("known category sets icon, label, and dataset", () => {
    profile.setCategory("person");
    const badge = document.getElementById("category-badge");
    expect(badge.querySelector("i").className).toBe("fa-solid fa-user");
    expect(badge.querySelector(".badge__label").textContent).toBe("Person");
    expect(badge.dataset.category).toBe("person");
  });

  test("unknown category falls back to fa-circle-nodes", () => {
    profile.setCategory("nonsense");
    const badge = document.getElementById("category-badge");
    expect(badge.querySelector("i").className).toBe("fa-solid fa-circle-nodes");
  });
});

describe("advanceProgress", () => {
  beforeEach(() => {
    const stages = ["categorized", "queries", "searching", "fetching", "profile"];
    document.body.innerHTML = `<ol id="progress-strip">${stages
      .map((s) => `<li class="progress-step" data-stage="${s}"></li>`)
      .join("")}</ol>`;
  });

  test("marks completed steps done and current step active", () => {
    profile.advanceProgress("searching");
    const steps = [...document.querySelectorAll(".progress-step")];
    expect(steps[0].className).toBe("progress-step is-done");
    expect(steps[1].className).toBe("progress-step is-done");
    expect(steps[2].className).toBe("progress-step is-active");
    expect(steps[3].className).toBe("progress-step");
    expect(steps[4].className).toBe("progress-step");
  });

  test("invalid stage is a no-op", () => {
    const before = [...document.querySelectorAll(".progress-step")].map((s) => s.className);
    profile.advanceProgress("invalid");
    const after = [...document.querySelectorAll(".progress-step")].map((s) => s.className);
    expect(after).toEqual(before);
  });
});
