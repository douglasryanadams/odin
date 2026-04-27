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
  const baseOpts = { label: "S", leftLabel: "L", rightLabel: "R" };

  test("positive value prefixes with + and renders end labels", () => {
    const wrap = profile.buildSentimentGauge({ ...baseOpts, value: 0.32 });
    expect(wrap.querySelector(".gauge__value").textContent).toBe("+32");
    expect(wrap.querySelector(".gauge__marker").style.left).toBe("66%");
    expect(wrap.querySelector(".gauge__end--left").textContent).toBe("L");
    expect(wrap.querySelector(".gauge__end--right").textContent).toBe("R");
  });

  test("negative value keeps native sign", () => {
    const wrap = profile.buildSentimentGauge({ ...baseOpts, value: -0.5 });
    expect(wrap.querySelector(".gauge__value").textContent).toBe("-50");
    expect(wrap.querySelector(".gauge__marker").style.left).toBe("25%");
  });

  test("zero renders no sign prefix", () => {
    const wrap = profile.buildSentimentGauge({ ...baseOpts, value: 0 });
    expect(wrap.querySelector(".gauge__value").textContent).toBe("0");
  });

  test("neutral=true adds the gauge__track--neutral class", () => {
    const wrap = profile.buildSentimentGauge({ ...baseOpts, value: 0, neutral: true });
    expect(wrap.querySelector(".gauge__track--neutral")).not.toBeNull();
  });

  test("neutral defaults to false (no neutral class)", () => {
    const wrap = profile.buildSentimentGauge({ ...baseOpts, value: 0 });
    expect(wrap.querySelector(".gauge__track--neutral")).toBeNull();
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

describe("renderAssessment", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <article id="card-subject-compass">
        <div class="assessment-gauges"></div>
      </article>
      <article id="card-source-audit">
        <div class="assessment-gauges"></div>
        <ul class="caveats-list" data-empty="No caveats."></ul>
      </article>
    `;
  });

  const sample = {
    confidence: 0.78,
    public_sentiment: 0.32,
    subject_political_bias: -0.2,
    source_political_bias: 0.1,
    law_chaos: -0.6,
    good_evil: 0.7,
    caveats: ["c1", "c2"],
  };

  test("Subject Compass renders the four subject gauges with expected labels and end labels", () => {
    profile.renderAssessment(sample);
    const labels = [
      ...document.querySelectorAll("#card-subject-compass .gauge__label"),
    ].map((n) => n.textContent);
    expect(labels).toEqual(["Public sentiment", "Political lean", "Order", "Morality"]);
    const endLeft = [
      ...document.querySelectorAll("#card-subject-compass .gauge__end--left"),
    ].map((n) => n.textContent);
    const endRight = [
      ...document.querySelectorAll("#card-subject-compass .gauge__end--right"),
    ].map((n) => n.textContent);
    expect(endLeft).toEqual(["Negative", "Left", "Lawful", "Evil"]);
    expect(endRight).toEqual(["Positive", "Right", "Chaotic", "Good"]);
  });

  test("political/alignment gauges use the neutral track; sentiment does not", () => {
    profile.renderAssessment(sample);
    const tracks = [
      ...document.querySelectorAll("#card-subject-compass .gauge__track"),
    ];
    // Order: sentiment, political, order, morality
    expect(tracks[0].classList.contains("gauge__track--neutral")).toBe(false);
    expect(tracks[1].classList.contains("gauge__track--neutral")).toBe(true);
    expect(tracks[2].classList.contains("gauge__track--neutral")).toBe(true);
    expect(tracks[3].classList.contains("gauge__track--neutral")).toBe(true);
  });

  test("Source Audit renders confidence + source lean with expected values", () => {
    profile.renderAssessment(sample);
    const labels = [
      ...document.querySelectorAll("#card-source-audit .gauge__label"),
    ].map((n) => n.textContent);
    expect(labels).toEqual(["Profile confidence", "Source political lean"]);
    const confidenceValue = document.querySelector(
      "#card-source-audit .gauge--confidence .gauge__value",
    );
    expect(confidenceValue.textContent).toBe("78%");
  });

  test("renders one li per caveat in the Source Audit card", () => {
    profile.renderAssessment({ ...sample, caveats: ["one", "two", "three"] });
    const items = document.querySelectorAll("#card-source-audit .caveats-list li");
    expect(items.length).toBe(3);
    expect(items[0].textContent).toBe("one");
  });

  test("empty caveats shows the data-empty fallback", () => {
    profile.renderAssessment({ ...sample, caveats: [] });
    const items = document.querySelectorAll("#card-source-audit .caveats-list li");
    expect(items.length).toBe(1);
    expect(items[0].textContent).toBe("No caveats.");
  });
});
