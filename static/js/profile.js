// Odin profile page — SSE handler + content rendering.
// Layout: anchored sidebar (subject + Subject Compass + Source Audit) plus a
// longform main article column with exposition, significant events, and
// click-to-expand findings.

const STAGES = [
  "categorized",
  "queries",
  "searching",
  "fetching",
  "synthesizing",
  "assessing",
];

const CATEGORY_ICONS = {
  person: "fa-user",
  place: "fa-location-dot",
  event: "fa-calendar",
  other: "fa-circle-nodes",
};

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
  const yyyy = now.getFullYear();
  const mm = String(now.getMonth() + 1).padStart(2, "0");
  const dd = String(now.getDate()).padStart(2, "0");
  node.textContent = `${yyyy}-${mm}-${dd}`;
  node.setAttribute("datetime", node.textContent);
}

function advanceProgress(stage) {
  const strip = $("progress-strip");
  if (!strip) return;
  const targetIndex = STAGES.indexOf(stage);
  if (targetIndex === -1) return;
  strip.querySelectorAll(".progress-step").forEach((step, i) => {
    step.classList.remove("is-active", "is-done");
    if (i < targetIndex) step.classList.add("is-done");
    else if (i === targetIndex) step.classList.add("is-active");
  });
}

function completeProgress() {
  const strip = $("progress-strip");
  if (!strip) return;
  strip.querySelectorAll(".progress-step").forEach((step) => {
    step.classList.remove("is-active");
    step.classList.add("is-done");
  });
  strip.classList.add("is-complete");
  strip.hidden = true;
}

function failProgress(message) {
  const strip = $("progress-strip");
  if (!strip) return;
  strip.classList.add("is-failed");
  const labels = strip.querySelectorAll(".progress-step__label");
  if (labels.length) labels[labels.length - 1].textContent = message;
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

function renderExposition(summary) {
  const node = $("exposition");
  if (!node) return;
  node.replaceChildren();
  const paragraphs = (summary || "").split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean);
  if (!paragraphs.length) {
    return;
  }
  paragraphs.forEach((text, i) => {
    const p = el("p", i === 0 ? "profile__lede dropcap" : null, text);
    node.appendChild(p);
  });
}

function renderEvents(listEl, items) {
  listEl.replaceChildren();
  if (!items || !items.length) {
    listEl.appendChild(el("li", "events__empty muted", listEl.dataset.empty || ""));
    return;
  }
  items.forEach((item) => {
    const li = el("li", "events__item");
    li.appendChild(el("time", "events__date mono", item.date));
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
    highlightsHint.textContent = `${data.highlights.length} items · click any for detail`;
  }
  const lowlightsHint = $("lowlights-hint");
  if (lowlightsHint && data.lowlights && data.lowlights.length) {
    lowlightsHint.textContent = `${data.lowlights.length} items · click any for detail`;
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
      buildGauge("Profile confidence", Math.round(data.confidence * 100), "gauge--confidence"),
    );
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
  const auditPct = $("audit-pct");
  if (auditPct) auditPct.textContent = `${Math.round(data.confidence * 100)}%`;

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

function buildGauge(label, percent, modifier) {
  const wrap = el("div", `gauge ${modifier}`);
  const top = el("div", "gauge__head");
  top.appendChild(el("span", "gauge__label", label));
  top.appendChild(el("span", "gauge__value mono", `${percent}%`));
  wrap.appendChild(top);
  const track = el("div", "gauge__track");
  const fill = el("div", "gauge__fill");
  fill.style.width = `${percent}%`;
  track.appendChild(fill);
  wrap.appendChild(track);
  return wrap;
}

function buildSentimentGauge({ label, leftLabel, rightLabel, value, neutral = false }) {
  const wrap = el("div", "gauge gauge--sentiment");
  wrap.appendChild(el("span", "gauge__label", label));
  const display =
    value > 0 ? `+${(value * 100).toFixed(0)}` : `${(value * 100).toFixed(0)}`;
  wrap.appendChild(el("span", "gauge__value mono", display));
  const barRow = el("div", "gauge__bar-row");
  barRow.appendChild(el("span", "gauge__end gauge__end--left", leftLabel));
  const trackClasses = neutral
    ? "gauge__track gauge__track--diverging gauge__track--neutral"
    : "gauge__track gauge__track--diverging";
  const track = el("div", trackClasses);
  const marker = el("span", "gauge__marker");
  marker.style.left = `${50 + value * 50}%`;
  track.appendChild(marker);
  barRow.appendChild(track);
  barRow.appendChild(el("span", "gauge__end gauge__end--right", rightLabel));
  wrap.appendChild(barRow);
  return wrap;
}

// Each pipeline event names the step the user should now see as in-progress
// (`active`), or marks the run complete (`complete: true`). Render hooks attach
// content rendering to specific events. Keeping wire-event semantics in this
// table keeps the dispatcher trivially testable.
const EVENT_HANDLERS = {
  categorized:  { active: "queries",     render: (d) => setCategory(d.category) },
  queries:      { active: "searching" },
  searching:    { active: "fetching" },
  fetching:     { active: "fetching" },
  synthesizing: { active: "synthesizing" },
  profile:      { active: "assessing", render: renderProfile },
  assessing:    { active: "assessing" },
  assessment:   { complete: true, render: renderAssessment },
  done:         { complete: true },
};

function handleEvent(data) {
  const handler = EVENT_HANDLERS[data.type];
  if (!handler) return false;
  if (handler.active) advanceProgress(handler.active);
  if (handler.render) handler.render(data);
  if (handler.complete) completeProgress();
  return true;
}

function startStream(query) {
  const es = new EventSource("/profile/stream?q=" + encodeURIComponent(query));

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
  if (meta && meta.content) startStream(meta.content);
});
