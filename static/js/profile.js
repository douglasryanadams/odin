// Odin profile page — SSE handler + content rendering.
// Layout: anchored sidebar (subject + Subject Compass + Source Audit) plus a
// longform main article column with exposition, significant events, and
// click-to-expand findings.
//
// Visuals after the Matrix rebrand:
//   * Pipeline progress is a single-line ASCII bar with six "==========" segments
//     separated by "·". The active segment fills char-by-char and carries a
//     blinking "▒/░" cursor at the leading edge. profile.js drives the render
//     via requestAnimationFrame so the bar feels alive between SSE events.
//   * Compass + Source-audit gauges are single-line ASCII rules ("···▓···"
//     for positive gauges, "──·──▓─" for divergent gauges) with a phosphor
//     "▓" marker glyph at the value position. No filled bars.

const STAGES = [
  "categorized",
  "queries",
  "searching",
  "fetching",
  "synthesizing",
  "assessing",
];

const STAGE_LABELS = {
  categorized:  "categorize",
  queries:      "plan queries",
  searching:    "search",
  fetching:     "load pages",
  synthesizing: "synthesize",
  assessing:    "audit",
};

const CATEGORY_ICONS = {
  person: "fa-user",
  place: "fa-location-dot",
  event: "fa-calendar",
  other: "fa-circle-nodes",
};

// Display names for search backend identifiers, used when reporting which
// ones did not shape a profile (see renderSourceNote).
const BACKEND_DISPLAY_NAMES = {
  brave: "Brave Search",
  wikipedia: "Wikipedia",
};

// Visual layout for the ASCII progress bar
const SEG_WIDTH = 10;       // chars per stage segment
const STAGE_FILL_MS = 2400; // time to visually fill one segment while waiting

// Layout for the ASCII gauges
const RULE_WIDTH = 24;

function $(id) {
  return document.getElementById(id);
}

function el(tag, className, content) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content !== undefined) node.textContent = content;
  return node;
}

function setSynthTime() {
  const node = $("synth-time");
  if (!node) return;
  const now = new Date();
  const yyyy = now.getUTCFullYear();
  const mm = String(now.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(now.getUTCDate()).padStart(2, "0");
  const hh = String(now.getUTCHours()).padStart(2, "0");
  const mi = String(now.getUTCMinutes()).padStart(2, "0");
  const iso = `${yyyy}-${mm}-${dd}T${hh}:${mi}Z`;
  node.textContent = `[${iso}]`;
  node.setAttribute("datetime", iso);
}

// ---------------------------------------------------------------------------
// Pipeline progress — ASCII bar
// ---------------------------------------------------------------------------

let _progressIdx = 0;
let _progressStart = 0;
let _progressState = "running"; // "running" | "done" | "failed"
let _progressFailMsg = null;
let _progressRAF = null;

function _progressBarEl() {
  return $("progress-strip");
}

function _renderProgressBar() {
  const barEl = _progressBarEl();
  if (!barEl) return;

  const totalSegs = STAGES.length;
  const failed = _progressState === "failed";
  const done = _progressState === "done";

  const sub = done
    ? 0
    : Math.min(1, (performance.now() - _progressStart) / STAGE_FILL_MS);

  const segs = STAGES.map((_, i) => {
    if (done) {
      return '<span class="progress-bar__filled">' + "=".repeat(SEG_WIDTH) + "</span>";
    }
    if (failed && i === _progressIdx) {
      return '<span class="progress-bar__failed">' + "X".repeat(SEG_WIDTH) + "</span>";
    }
    if (i < _progressIdx) {
      return '<span class="progress-bar__filled">' + "=".repeat(SEG_WIDTH) + "</span>";
    }
    if (i === _progressIdx && !failed) {
      const fill = Math.floor(sub * SEG_WIDTH);
      const blink = Math.floor(performance.now() / 350) % 2 === 0;
      const cursorChar = blink ? "▒" : "░";
      const filled = '<span class="progress-bar__filled">' + "=".repeat(fill) + "</span>";
      const cursor = '<span class="progress-bar__cursor">' + cursorChar + "</span>";
      const rest = " ".repeat(Math.max(0, SEG_WIDTH - fill - 1));
      return filled + cursor + rest;
    }
    return " ".repeat(SEG_WIDTH);
  });

  const bar = "[" + segs.join("·") + "]";

  let labelText;
  if (failed) {
    labelText = _progressFailMsg || "failed";
  } else if (done) {
    labelText = " 100%  complete";
  } else {
    const stageProgress = (_progressIdx + sub) / totalSegs;
    const pct = Math.floor(stageProgress * 100);
    const stageName = STAGE_LABELS[STAGES[_progressIdx]] || STAGES[_progressIdx];
    labelText = String(pct).padStart(3, " ") + "%  " + stageName;
  }

  // Render the bar and label as two block-level siblings so the label
  // sits on its own line below the bar. Earlier iterations rendered
  // them on one line, which let the label tail extend past .profile__main
  // and visually slip behind the sidebar column on narrow viewports.
  barEl.innerHTML =
    '<span class="progress-bar__line">' + bar + "</span>" +
    '<span class="progress-bar__label">' + labelText + "</span>";
}

function _scheduleProgressRender() {
  if (_progressRAF !== null) return;
  const tick = () => {
    _progressRAF = null;
    if (_progressState !== "running") return;
    _renderProgressBar();
    // Keep ticking while the current segment is still filling, or to
    // keep the cursor blinking on the leading edge once it tops out.
    _progressRAF = requestAnimationFrame(tick);
  };
  _progressRAF = requestAnimationFrame(tick);
}

function advanceProgress(stage) {
  const idx = STAGES.indexOf(stage);
  if (idx === -1) return;
  if (_progressState !== "running") return;
  if (idx < _progressIdx) return;
  _progressIdx = idx;
  _progressStart = performance.now();
  _renderProgressBar();
  _scheduleProgressRender();
}

// Reset the progress-bar internal state. Called by the DOMContentLoaded
// bootstrap so a navigation back to /profile starts from scratch, and by
// the vitest suite between describe blocks so module-level state doesn't
// leak across tests. The eslint disable below silences "unused" — the
// function is referenced via the vm sandbox from tests/js/loadProfile.js.
// eslint-disable-next-line no-unused-vars
function resetProgress() {
  _progressIdx = 0;
  _progressStart = performance.now();
  _progressState = "running";
  _progressFailMsg = null;
  if (_progressRAF !== null) {
    cancelAnimationFrame(_progressRAF);
    _progressRAF = null;
  }
}

function completeProgress() {
  _progressState = "done";
  if (_progressRAF !== null) {
    cancelAnimationFrame(_progressRAF);
    _progressRAF = null;
  }
  _renderProgressBar();
  const strip = $("progress-strip");
  if (strip) {
    strip.classList.add("is-complete");
    strip.hidden = true;
  }
}

function failProgress(message) {
  _progressState = "failed";
  _progressFailMsg = message || "failed";
  if (_progressRAF !== null) {
    cancelAnimationFrame(_progressRAF);
    _progressRAF = null;
  }
  _renderProgressBar();
  const strip = $("progress-strip");
  if (strip) strip.classList.add("is-failed");
}

function setCategory(category) {
  const badge = $("category-badge");
  if (badge) {
    const icon = badge.querySelector("i");
    const label = badge.querySelector(".badge__label");
    const cls = CATEGORY_ICONS[category] || CATEGORY_ICONS.other;
    if (icon) icon.className = `fa-solid ${cls}`;
    if (label) label.textContent = category.charAt(0).toUpperCase() + category.slice(1);
    badge.dataset.category = category;
  }
  const kicker = $("kicker-category");
  if (kicker) kicker.textContent = category.charAt(0).toUpperCase() + category.slice(1);
}

// A backend can come up empty for many reasons (error, timeout, or simply
// nothing relevant); the note only states the fact a reader cares about —
// which backends did not shape this profile — not a guess at why.
function renderSourceNote(data) {
  const note = $("source-note");
  if (!note) return;
  const missing = data.missing_backends || [];
  if (!missing.length) {
    note.hidden = true;
    return;
  }
  const names = missing.map((id) => BACKEND_DISPLAY_NAMES[id] || id);
  const joined =
    names.length === 1 ? names[0] : `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`;
  note.textContent = `${joined} did not return results for this search.`;
  note.hidden = false;
}

function renderEvents(listEl, items) {
  listEl.replaceChildren();
  if (!items || !items.length) {
    listEl.appendChild(el("li", "events__empty muted", listEl.dataset.empty || ""));
    return;
  }
  items.forEach((item) => {
    const li = el("li", "events__item");
    li.appendChild(el("time", "events__date mono", `[${item.date}]`));
    const body = el("div", "events__body");
    body.appendChild(el("p", "events__text", item.event));
    li.appendChild(body);
    listEl.appendChild(li);
  });
  const counter = listEl.matches("#section-events .events")
    ? $("events-count")
    : null;
  if (counter) counter.textContent = `${items.length} events`;
}

// Render a click-to-expand finding row using a native <details>/<summary>.
// Each row collapses to (label) + title + brief; expansion reveals the longer
// `detail` field with a left-rail accent.
function renderFinding(label, item, kind) {
  const details = el("details", "finding");
  const summary = el("summary");

  const labelEl = el("span", "finding__label" + (kind === "neg" ? " finding__label--neg" : ""));
  labelEl.textContent = `${kind === "neg" ? "−" : "+"} ${label}`;
  summary.appendChild(labelEl);

  const titleWrap = el("div", "finding__title");
  const strong = el("strong");
  strong.textContent = item.title ? `${item.title}.` : "";
  titleWrap.appendChild(strong);
  const brief = el("span", "finding__brief", item.description || "");
  titleWrap.appendChild(brief);
  summary.appendChild(titleWrap);

  const more = el("span", "finding__more");
  more.appendChild(el("span", "finding__chev", "▸"));
  more.appendChild(el("span", "finding__more-label"));
  summary.appendChild(more);

  details.appendChild(summary);

  const detail = el("div", "finding__detail");
  detail.appendChild(el("p", null, item.detail || ""));
  details.appendChild(detail);

  return details;
}

function renderFindings(listEl, items, kind) {
  listEl.replaceChildren();
  if (!items || !items.length) {
    listEl.appendChild(el("li", "findings__empty muted", listEl.dataset.empty || ""));
    return;
  }
  items.forEach((item, idx) => {
    const li = el("li", "findings__item");
    li.appendChild(renderFinding(String(idx + 1).padStart(2, "0"), item, kind));
    listEl.appendChild(li);
  });
}

function domainOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function renderCitations(listEl, items) {
  listEl.replaceChildren();
  if (!items || !items.length) {
    listEl.appendChild(el("li", "citations__empty muted", listEl.dataset.empty || ""));
    return;
  }
  items.forEach((item) => {
    const domain = domainOf(item.url);
    const li = el("li", "citations__item");
    const link = el("a", "citations__link");
    link.href = item.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = item.title || domain;
    li.appendChild(link);
    li.appendChild(el("span", "citations__domain mono", domain));
    li.appendChild(el("p", "citations__snippet muted", item.snippet || ""));
    listEl.appendChild(li);
  });
  const counter = $("sources-count");
  if (counter) counter.textContent = `${items.length} cited`;
}

function renderProfile(data) {
  const name = data.name || "";
  const sidebarName = $("sidebar-name");
  if (sidebarName) sidebarName.textContent = name;
  const subjectName = $("subject-name");
  if (subjectName) subjectName.textContent = name;

  const deck = $("summary");
  if (deck) {
    deck.replaceChildren();
    // Use the first paragraph as the deck; the rest go into the exposition.
    const paragraphs = (data.summary || "").split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean);
    if (paragraphs.length) {
      deck.textContent = paragraphs[0];
    }
  }
  // Render any remaining paragraphs into the exposition area.
  const exposition = $("exposition");
  if (exposition) {
    exposition.replaceChildren();
    const paragraphs = (data.summary || "").split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean);
    paragraphs.slice(1).forEach((text, i) => {
      const p = el("p", i === 0 ? "dropcap" : null, text);
      exposition.appendChild(p);
    });
  }

  setCategory(data.category);

  const events = document.querySelector("#section-events .events");
  if (events) renderEvents(events, data.timeline || []);

  const hl = document.querySelector("#section-highlights .findings");
  const ll = document.querySelector("#section-lowlights .findings");
  if (hl) renderFindings(hl, data.highlights || [], "pos");
  if (ll) renderFindings(ll, data.lowlights || [], "neg");

  const sources = document.querySelector("#section-sources .citations");
  if (sources) renderCitations(sources, data.citations || []);
  const bylineSources = $("byline-sources");
  if (bylineSources) bylineSources.textContent = String((data.citations || []).length);

  const highlightsHint = $("highlights-hint");
  if (highlightsHint && data.highlights && data.highlights.length) {
    highlightsHint.textContent = `${data.highlights.length} items // click any for detail`;
  }
  const lowlightsHint = $("lowlights-hint");
  if (lowlightsHint && data.lowlights && data.lowlights.length) {
    lowlightsHint.textContent = `${data.lowlights.length} items // click any for detail`;
  }
}

function renderAssessment(data) {
  const subjectGauges = document.querySelector("#subject-compass .assessment-gauges");
  if (subjectGauges) {
    subjectGauges.replaceChildren();
    subjectGauges.appendChild(
      buildSentimentGauge({
        label: "Public sentiment",
        leftLabel: "Negative",
        rightLabel: "Positive",
        value: data.public_sentiment,
      }),
    );
    subjectGauges.appendChild(
      buildSentimentGauge({
        label: "Political lean",
        leftLabel: "Left",
        rightLabel: "Right",
        value: data.subject_political_bias,
        neutral: true,
      }),
    );
    subjectGauges.appendChild(
      buildSentimentGauge({
        label: "Order",
        leftLabel: "Lawful",
        rightLabel: "Chaotic",
        value: data.law_chaos,
        neutral: true,
      }),
    );
    subjectGauges.appendChild(
      buildSentimentGauge({
        label: "Morality",
        leftLabel: "Evil",
        rightLabel: "Good",
        value: data.good_evil,
        neutral: true,
      }),
    );
  }
  const sourceGauges = document.querySelector("#source-audit .assessment-gauges");
  if (sourceGauges) {
    sourceGauges.replaceChildren();
    sourceGauges.appendChild(
      buildSentimentGauge({
        label: "Source political lean",
        leftLabel: "Left",
        rightLabel: "Right",
        value: data.source_political_bias,
        neutral: true,
      }),
    );
  }
  const caveats = document.querySelector("#source-audit .profile__caveats");
  if (caveats) renderCaveats(caveats, data.caveats || []);
}

function renderCaveats(listEl, items) {
  listEl.replaceChildren();
  if (!items.length) {
    listEl.appendChild(el("li", "profile__caveats-empty muted", listEl.dataset.empty || ""));
    return;
  }
  items.forEach((c) => {
    const li = el("li");
    const details = el("details", "caveat");
    const summary = el("summary");
    summary.appendChild(el("span", "caveat__brief", c.brief || ""));
    const more = el("span", "caveat__more");
    more.appendChild(el("span", "caveat__chev", "▸"));
    more.appendChild(el("span", "caveat__more-label"));
    summary.appendChild(more);
    details.appendChild(summary);
    const detail = el("div", "caveat__detail");
    detail.appendChild(el("p", null, c.detail || ""));
    details.appendChild(detail);
    li.appendChild(details);
    listEl.appendChild(li);
  });
}

// ---------------------------------------------------------------------------
// ASCII divergent sentiment gauge
// ---------------------------------------------------------------------------

function _markerSpan() {
  return '<span class="gauge-line__marker">▓</span>';
}

function buildSentimentGauge({ label, leftLabel, rightLabel, value, neutral = false }) {
  const center = Math.floor(RULE_WIDTH / 2);
  // value is -1..+1; map to char position with center at midpoint.
  const pos = Math.max(
    0,
    Math.min(RULE_WIDTH - 1, center + Math.round(value * center)),
  );

  let ruleHtml = "";
  for (let i = 0; i < RULE_WIDTH; i++) {
    if (i === pos) {
      ruleHtml += _markerSpan();
    } else if (i === center && pos !== center) {
      ruleHtml += "·"; // mark center divider when the marker isn't already there
    } else {
      ruleHtml += "─";
    }
  }

  const cls =
    "gauge-line gauge-line--divergent" + (neutral ? " gauge-line--neutral" : "");
  const wrap = el("div", cls);
  wrap.appendChild(el("span", "gauge-line__label", label));
  const display =
    value > 0 ? `+${(value * 100).toFixed(0)}` : `${(value * 100).toFixed(0)}`;
  wrap.appendChild(el("span", "gauge-line__value mono", display));

  const row = el("div", "gauge-line__row");
  row.appendChild(el("span", "gauge-line__end gauge-line__end--left", leftLabel));
  const rule = document.createElement("span");
  rule.className = "gauge-line__rule";
  rule.innerHTML = ruleHtml;
  row.appendChild(rule);
  row.appendChild(el("span", "gauge-line__end gauge-line__end--right", rightLabel));
  wrap.appendChild(row);
  return wrap;
}

// Each pipeline event names the step the user should now see as in-progress
// (`active`), or marks the run complete (`complete: true`). Render hooks attach
// content rendering to specific events. Keeping wire-event semantics in this
// table keeps the dispatcher trivially testable.
const EVENT_HANDLERS = {
  categorized:  { active: "queries",     render: (d) => setCategory(d.category) },
  queries:      { active: "searching" },
  searching:    { active: "fetching", render: renderSourceNote },
  fetching:     { active: "fetching" },
  synthesizing: { active: "synthesizing" },
  profile:      { active: "assessing", render: renderProfile },
  assessing:    { active: "assessing" },
  assessment:   { complete: true, render: renderAssessment },
  done:         { complete: true },
  // Deep-research-only stages: full narration is slice 3's job — for now
  // these just keep the progress bar moving so a multi-round run doesn't
  // look stalled during the extra rounds.
  draft_synthesizing: { active: "synthesizing" },
  deep_gap_analysis:  { active: "synthesizing" },
  deep_searching:     { active: "searching" },
  deep_fetching:      { active: "fetching" },
};

function handleEvent(data) {
  const handler = EVENT_HANDLERS[data.type];
  if (!handler) return false;
  if (handler.active) advanceProgress(handler.active);
  if (handler.render) handler.render(data);
  if (handler.complete) completeProgress();
  return true;
}

function startStream(query, deep) {
  const params = new URLSearchParams({ q: query });
  if (deep) params.set("deep", "true");
  const es = new EventSource("/profile/stream?" + params.toString());

  es.onmessage = (e) => {
    const data = JSON.parse(e.data);
    if (data.type === "rate_limited") {
      es.close();
      window.location.href = data.redirect || "/login?reason=limit";
      return;
    }
    if (data.type === "service_unavailable") {
      es.close();
      failProgress(data.message || "Odin is temporarily paused. Please try again later.");
      return;
    }
    handleEvent(data);
    if (data.type === "done") es.close();
  };

  es.onerror = () => {
    failProgress("Pipeline failed — try again.");
    const summary = $("summary");
    if (summary) {
      summary.replaceChildren();
      const a = el("a", "", "Return to search");
      a.href = "/";
      summary.appendChild(document.createTextNode("Something went wrong. "));
      summary.appendChild(a);
    }
    es.close();
  };
}

document.addEventListener("DOMContentLoaded", () => {
  setSynthTime();
  const meta = document.querySelector('meta[name="odin-query"]');
  const deepMeta = document.querySelector('meta[name="odin-deep"]');
  const deep = !!deepMeta && deepMeta.content === "true";
  if (meta && meta.content) startStream(meta.content, deep);
});
