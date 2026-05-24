import { beforeEach, describe, expect, test } from "vitest";
import { loadProfile } from "./loadProfile.js";

const profile = loadProfile();

// ---------------------------------------------------------------------------
// Minimal DOM scaffolding shared by tests that drive renderProfile / handleEvent.
// Mirrors the structure of src/odin/templates/profile.html after the Matrix
// rebrand: progress is a single .progress-bar element with a .progress-bar__line
// child that profile.js fills via innerHTML, and gauges use the .gauge-line
// (single-row ASCII rule) markup instead of the old .gauge / .gauge__fill bars.
// ---------------------------------------------------------------------------
function buildProfileDom() {
  document.body.innerHTML = `
    <span class="badge" id="category-badge">
      <i class="fa-solid fa-circle-nodes" aria-hidden="true"></i>
      <span class="badge__label">Pending…</span>
    </span>
    <span id="kicker-category"></span>
    <h1 id="subject-name"></h1>
    <h1 id="sidebar-name"></h1>
    <p id="summary"></p>
    <div id="exposition"></div>
    <span id="byline-sources"></span>
    <div id="progress-strip" class="progress-bar"></div>
    <section id="section-events"><span id="events-count"></span><ol class="events" data-empty="none"></ol></section>
    <section id="section-highlights"><span id="highlights-hint"></span><ul class="findings" data-empty="none"></ul></section>
    <section id="section-lowlights"><span id="lowlights-hint"></span><ul class="findings" data-empty="none"></ul></section>
    <section id="section-sources"><span id="sources-count"></span><ol class="citations" data-empty="none"></ol></section>
    <div id="subject-compass"><div class="assessment-gauges"></div></div>
    <div id="source-audit">
      <span id="audit-pct"></span>
      <div class="assessment-gauges"></div>
      <ul class="profile__caveats" data-empty="No caveats."></ul>
    </div>
  `;
}

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
  test("renders label, percent value, and a marker in the rule", () => {
    const wrap = profile.buildGauge("Conf", 78, "gauge-line--confidence");
    expect(wrap.querySelector(".gauge-line__label").textContent).toBe("Conf");
    expect(wrap.querySelector(".gauge-line__value").textContent).toBe("78%");
    expect(wrap.querySelector(".gauge-line__marker").textContent).toBe("▓");
    expect(wrap.className).toBe("gauge-line gauge-line--confidence");
  });

  test("rule length is the configured RULE_WIDTH and contains exactly one marker", () => {
    const wrap = profile.buildGauge("X", 50, "");
    const rule = wrap.querySelector(".gauge-line__rule");
    // textContent collapses the marker span's "▓" plus the surrounding dots.
    // RULE_WIDTH (24) chars total: 23 dots + 1 marker = 24.
    expect(rule.textContent.length).toBe(24);
    expect(rule.querySelectorAll(".gauge-line__marker").length).toBe(1);
  });

  test("100% places marker at the right end (last position)", () => {
    const wrap = profile.buildGauge("X", 100, "");
    const rule = wrap.querySelector(".gauge-line__rule");
    expect(rule.textContent[rule.textContent.length - 1]).toBe("▓");
  });
});

describe("buildSentimentGauge", () => {
  const baseOpts = { label: "S", leftLabel: "L", rightLabel: "R" };

  test("positive value prefixes with + and renders end labels", () => {
    const wrap = profile.buildSentimentGauge({ ...baseOpts, value: 0.32 });
    expect(wrap.querySelector(".gauge-line__value").textContent).toBe("+32");
    expect(wrap.querySelector(".gauge-line__end--left").textContent).toBe("L");
    expect(wrap.querySelector(".gauge-line__end--right").textContent).toBe("R");
    expect(wrap.querySelector(".gauge-line__marker").textContent).toBe("▓");
  });

  test("negative value keeps native sign and places marker left of center", () => {
    const wrap = profile.buildSentimentGauge({ ...baseOpts, value: -0.5 });
    expect(wrap.querySelector(".gauge-line__value").textContent).toBe("-50");
    const rule = wrap.querySelector(".gauge-line__rule");
    // RULE_WIDTH=24, center=12, marker at 12 + round(-0.5*12) = 12 - 6 = 6.
    // textContent: 6 chars of "─" + "▓" + 5 chars + "·" (center) + 11 chars.
    expect(rule.textContent[6]).toBe("▓");
  });

  test("zero renders no sign prefix and marker sits at center", () => {
    const wrap = profile.buildSentimentGauge({ ...baseOpts, value: 0 });
    expect(wrap.querySelector(".gauge-line__value").textContent).toBe("0");
    const rule = wrap.querySelector(".gauge-line__rule");
    expect(rule.textContent[12]).toBe("▓");
  });

  test("neutral=true adds the gauge-line--neutral class", () => {
    const wrap = profile.buildSentimentGauge({ ...baseOpts, value: 0, neutral: true });
    expect(wrap.classList.contains("gauge-line--neutral")).toBe(true);
  });

  test("neutral defaults to false (no neutral class)", () => {
    const wrap = profile.buildSentimentGauge({ ...baseOpts, value: 0 });
    expect(wrap.classList.contains("gauge-line--neutral")).toBe(false);
  });
});

describe("setCategory", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <span class="badge badge--category" id="category-badge">
        <i class="fa-solid fa-circle-nodes" aria-hidden="true"></i>
        <span class="badge__label">Pending…</span>
      </span>
      <span id="kicker-category"></span>
    `;
  });

  test("known category sets badge icon, label, dataset, and kicker text", () => {
    profile.setCategory("person");
    const badge = document.getElementById("category-badge");
    expect(badge.querySelector("i").className).toBe("fa-solid fa-user");
    expect(badge.querySelector(".badge__label").textContent).toBe("Person");
    expect(badge.dataset.category).toBe("person");
    expect(document.getElementById("kicker-category").textContent).toBe("Person");
  });

  test("unknown category falls back to fa-circle-nodes", () => {
    profile.setCategory("nonsense");
    const badge = document.getElementById("category-badge");
    expect(badge.querySelector("i").className).toBe("fa-solid fa-circle-nodes");
  });
});

describe("advanceProgress", () => {
  beforeEach(() => {
    profile.resetProgress();
    document.body.innerHTML =
      '<div id="progress-strip" class="progress-bar"></div>';
  });

  function barHtml() {
    return document.getElementById("progress-strip").innerHTML;
  }

  test("renders filled segments for completed stages and a cursor on the active one", () => {
    profile.advanceProgress("searching");
    const html = barHtml();
    // Two prior stages should be fully filled
    expect(html).toContain('<span class="progress-bar__filled">==========</span>');
    // Active stage shows the blinking cursor
    expect(html).toMatch(/<span class="progress-bar__cursor">[▒░]<\/span>/);
    // Label should name the current stage
    expect(html).toContain("search");
    // Bar and label render as separate block-level siblings
    expect(html).toContain('<span class="progress-bar__line">');
    expect(html).toContain('<span class="progress-bar__label">');
  });

  test("invalid stage is a no-op", () => {
    profile.advanceProgress("categorized");
    const before = barHtml();
    profile.advanceProgress("invalid");
    expect(barHtml()).toBe(before);
  });
});

describe("handleEvent", () => {
  beforeEach(() => {
    profile.resetProgress();
    buildProfileDom();
  });

  function lineText() {
    return document.getElementById("progress-strip").textContent;
  }

  test("categorized renders the bar at stage 1 (plan queries) and sets the badge", () => {
    profile.handleEvent({ type: "categorized", category: "person" });
    expect(lineText()).toContain("plan queries");
    expect(document.querySelector(".badge__label").textContent).toBe("Person");
  });

  test("synthesizing advances the bar to the synthesize stage", () => {
    profile.handleEvent({ type: "synthesizing" });
    expect(lineText()).toContain("synthesize");
  });

  test("profile event renders the deck and advances bar to assessing", () => {
    profile.handleEvent({
      type: "profile",
      name: "Subject",
      summary: "First paragraph.\n\nSecond paragraph.",
      category: "person",
      highlights: [],
      lowlights: [],
      timeline: [],
      citations: [],
    });
    expect(document.getElementById("subject-name").textContent).toBe("Subject");
    expect(document.getElementById("sidebar-name").textContent).toBe("Subject");
    expect(document.getElementById("summary").textContent).toBe("First paragraph.");
    expect(document.querySelectorAll("#exposition p").length).toBe(1);
    expect(lineText()).toContain("audit");
  });

  test("assessment event completes the bar and renders gauges + caveats", () => {
    profile.handleEvent({
      type: "assessment",
      confidence: 0.5,
      public_sentiment: 0,
      subject_political_bias: 0,
      source_political_bias: 0,
      law_chaos: 0,
      good_evil: 0,
      caveats: [{ brief: "careful", detail: "note" }],
    });
    expect(document.getElementById("progress-strip").classList.contains("is-complete")).toBe(true);
    expect(document.querySelectorAll("#subject-compass .gauge-line__label").length).toBe(4);
    expect(document.getElementById("audit-pct").textContent).toBe("50%");
  });

  test("done force-completes the bar if assessment never arrives", () => {
    profile.handleEvent({ type: "synthesizing" });
    profile.handleEvent({ type: "done" });
    expect(document.getElementById("progress-strip").classList.contains("is-complete")).toBe(true);
  });

  test("unknown event type returns false and is a no-op", () => {
    expect(profile.handleEvent({ type: "mystery" })).toBe(false);
  });
});

describe("renderProfile findings + events", () => {
  beforeEach(() => {
    profile.resetProgress();
    buildProfileDom();
  });

  test("highlights render as <details> rows with title, brief and detail", () => {
    profile.renderProfile({
      name: "x",
      category: "person",
      summary: "lede",
      highlights: [
        {
          title: "Algorithm A (1843)",
          description: "First algorithm intended for a machine.",
          detail: "Lovelace's Note G describes a procedure to compute Bernoulli numbers.",
        },
      ],
      lowlights: [],
      timeline: [],
      citations: [],
    });
    const rows = document.querySelectorAll("#section-highlights .findings details.finding");
    expect(rows.length).toBe(1);
    expect(rows[0].querySelector(".finding__label").textContent).toBe("+ 01");
    expect(rows[0].querySelector(".finding__title strong").textContent).toBe(
      "Algorithm A (1843).",
    );
    expect(rows[0].querySelector(".finding__brief").textContent).toBe(
      "First algorithm intended for a machine.",
    );
    expect(rows[0].querySelector(".finding__detail p").textContent).toContain("Bernoulli");
    // The persistent click affordance is present (chevron + More/Less label slot).
    expect(rows[0].querySelector(".finding__more .finding__chev")).not.toBeNull();
    expect(rows[0].querySelector(".finding__more-label")).not.toBeNull();
  });

  test("lowlights use a negative label (− NN)", () => {
    profile.renderProfile({
      name: "x",
      category: "person",
      summary: "",
      highlights: [],
      lowlights: [{ title: "Gambling", description: "Lost money.", detail: "..." }],
      timeline: [],
      citations: [],
    });
    const label = document.querySelector("#section-lowlights .finding__label");
    expect(label.classList.contains("finding__label--neg")).toBe(true);
    expect(label.textContent).toBe("− 01");
  });

  test("timeline renders into Significant events with bracketed dates", () => {
    profile.renderProfile({
      name: "x",
      category: "person",
      summary: "",
      highlights: [],
      lowlights: [],
      timeline: [
        { date: "1815-12-10", event: "Born" },
        { date: "1843", event: "Notes published" },
      ],
      citations: [],
    });
    const events = document.querySelectorAll("#section-events .events .events__item");
    expect(events.length).toBe(2);
    // Dates render bracketed (terminal-log feel) — "[1815-12-10]" not "1815-12-10"
    expect(events[0].querySelector(".events__date").textContent).toBe("[1815-12-10]");
    expect(events[1].querySelector(".events__date").textContent).toBe("[1843]");
    expect(document.getElementById("events-count").textContent).toBe("2 events");
  });

  test("multi-paragraph summary splits: p1 → deck, p2…N → exposition", () => {
    profile.renderProfile({
      name: "x",
      category: "person",
      summary: "lede line.\n\nsecond paragraph.\n\nthird paragraph.",
      highlights: [],
      lowlights: [],
      timeline: [],
      citations: [],
    });
    expect(document.getElementById("summary").textContent).toBe("lede line.");
    const paragraphs = document.querySelectorAll("#exposition p");
    expect(paragraphs.length).toBe(2);
    expect(paragraphs[0].textContent).toBe("second paragraph.");
    expect(paragraphs[1].textContent).toBe("third paragraph.");
  });
});

describe("renderAssessment", () => {
  beforeEach(() => {
    profile.resetProgress();
    buildProfileDom();
  });

  const sample = {
    confidence: 0.78,
    public_sentiment: 0.32,
    subject_political_bias: -0.2,
    source_political_bias: 0.1,
    law_chaos: -0.6,
    good_evil: 0.7,
    caveats: [
      { brief: "caveat one", detail: "explanation one" },
      { brief: "caveat two", detail: "explanation two" },
    ],
  };

  test("Subject Compass renders four sentiment gauges with expected labels", () => {
    profile.renderAssessment(sample);
    const labels = [
      ...document.querySelectorAll("#subject-compass .gauge-line__label"),
    ].map((n) => n.textContent);
    expect(labels).toEqual(["Public sentiment", "Political lean", "Order", "Morality"]);
  });

  test("Source Audit renders confidence + source lean, and sets audit-pct", () => {
    profile.renderAssessment(sample);
    const labels = [
      ...document.querySelectorAll("#source-audit .gauge-line__label"),
    ].map((n) => n.textContent);
    expect(labels).toEqual(["Profile confidence", "Source political lean"]);
    expect(
      document.querySelector("#source-audit .gauge-line--confidence .gauge-line__value").textContent,
    ).toBe("78%");
    expect(document.getElementById("audit-pct").textContent).toBe("78%");
  });

  test("caveats render as expandable <details> with brief + detail", () => {
    profile.renderAssessment(sample);
    const caveats = document.querySelectorAll("#source-audit .profile__caveats details.caveat");
    expect(caveats.length).toBe(2);
    expect(caveats[0].querySelector(".caveat__brief").textContent).toBe("caveat one");
    expect(caveats[0].querySelector(".caveat__detail p").textContent).toBe("explanation one");
    // Click affordance present.
    expect(caveats[0].querySelector(".caveat__more .caveat__chev")).not.toBeNull();
    expect(caveats[0].querySelector(".caveat__more-label")).not.toBeNull();
  });

  test("empty caveats render the data-empty fallback", () => {
    profile.renderAssessment({ ...sample, caveats: [] });
    const items = document.querySelectorAll("#source-audit .profile__caveats li");
    expect(items.length).toBe(1);
    expect(items[0].textContent).toBe("No caveats.");
  });
});
