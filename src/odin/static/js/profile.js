// Odin profile page — SSE handler + card rendering.

const STUB_DATA = true;

const STAGES = ["categorized", "queries", "searching", "fetching", "profile"];

const CATEGORY_ICONS = {
  person: "fa-user",
  place: "fa-location-dot",
  event: "fa-calendar",
  other: "fa-circle-nodes",
};

const STUB_MENTIONS = [
  { time: "2026-04-25 14:02", domain: "techcrunch.com", headline: "Profile cited in announcement coverage." },
  { time: "2026-04-23 09:11", domain: "nytimes.com", headline: "Mentioned in feature piece on the topic." },
  { time: "2026-04-19 22:48", domain: "hackernews.ycombinator.com", headline: "Discussion thread (217 comments)." },
];

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
  if (!badge) return;
  const icon = badge.querySelector("i");
  const label = badge.querySelector(".badge__label");
  const cls = CATEGORY_ICONS[category] || CATEGORY_ICONS.other;
  if (icon) icon.className = `fa-solid ${cls}`;
  if (label) label.textContent = category.charAt(0).toUpperCase() + category.slice(1);
  badge.dataset.category = category;
}

function renderHighlights(listEl, items) {
  listEl.replaceChildren();
  if (!items || !items.length) {
    listEl.appendChild(el("li", "hl-list__empty muted", listEl.dataset.empty || ""));
    return;
  }
  items.forEach((item) => {
    const li = el("li", "hl-list__item");
    li.appendChild(el("strong", "hl-list__title", item.title));
    li.appendChild(el("p", "hl-list__body", item.description));
    listEl.appendChild(li);
  });
}

function renderTimeline(listEl, items) {
  listEl.replaceChildren();
  if (!items || !items.length) {
    listEl.appendChild(el("li", "timeline__empty muted", listEl.dataset.empty || ""));
    return;
  }
  items.forEach((item) => {
    const li = el("li", "timeline__item");
    li.appendChild(el("span", "timeline__node", ""));
    li.appendChild(el("span", "timeline__date mono", item.date));
    li.appendChild(el("p", "timeline__event", item.event));
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
    listEl.appendChild(el("li", "source-item__empty muted", listEl.dataset.empty || ""));
    return;
  }
  items.forEach((item) => {
    const domain = domainOf(item.url);
    const li = el("li", "source-item");
    const link = el("a", "source-item__link");
    link.href = item.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.appendChild(el("span", "source-item__favicon", domain.charAt(0).toUpperCase()));
    const body = el("div", "source-item__body");
    body.appendChild(el("span", "source-item__domain mono", domain));
    body.appendChild(el("strong", "source-item__title", item.title || domain));
    body.appendChild(el("p", "source-item__snippet muted", item.snippet));
    link.appendChild(body);
    li.appendChild(link);
    listEl.appendChild(li);
  });
}

function renderProfile(data) {
  const summary = $("summary");
  if (summary) {
    summary.replaceChildren();
    summary.appendChild(document.createTextNode(data.summary));
  }
  setCategory(data.category);
  const hl = document.querySelector("#card-highlights .hl-list");
  const ll = document.querySelector("#card-lowlights .hl-list");
  const tl = document.querySelector("#card-timeline .timeline");
  const sources = document.querySelector("#card-sources .sources-list");
  if (hl) renderHighlights(hl, data.highlights);
  if (ll) renderHighlights(ll, data.lowlights);
  if (tl) renderTimeline(tl, data.timeline);
  if (sources) renderCitations(sources, data.citations || []);
  completeProgress();
  const strip = $("progress-strip");
  if (strip) strip.hidden = true;
}

function renderAssessment(data) {
  const subjectGauges = document.querySelector("#card-subject-compass .assessment-gauges");
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
  const sourceGauges = document.querySelector("#card-source-audit .assessment-gauges");
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
  const caveatsList = document.querySelector("#card-source-audit .caveats-list");
  if (caveatsList) {
    caveatsList.replaceChildren();
    if (!data.caveats || !data.caveats.length) {
      caveatsList.appendChild(
        el("li", "caveats-list__empty muted", caveatsList.dataset.empty || ""),
      );
    } else {
      data.caveats.forEach((c) => caveatsList.appendChild(el("li", "caveats-list__item", c)));
    }
  }
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

function renderStubMentions() {
  const list = document.querySelector("#card-mentions .mentions-list");
  if (!list) return;
  list.replaceChildren();
  STUB_MENTIONS.forEach((m) => {
    const li = el("li", "mention-item");
    li.appendChild(el("time", "mention-item__time mono", m.time));
    li.appendChild(el("span", "mention-item__domain", m.domain));
    li.appendChild(el("p", "mention-item__headline", m.headline));
    list.appendChild(li);
  });
}

function renderStubs() {
  if (!STUB_DATA) return;
  renderStubMentions();
}

function startStream(query) {
  const es = new EventSource("/profile/stream?q=" + encodeURIComponent(query));

  es.onmessage = (e) => {
    const data = JSON.parse(e.data);
    if (data.type === "categorized") {
      setCategory(data.category);
      advanceProgress("queries");
    } else if (data.type === "queries") {
      advanceProgress("searching");
    } else if (data.type === "searching") {
      advanceProgress("fetching");
    } else if (data.type === "fetching") {
      advanceProgress("profile");
    } else if (data.type === "profile") {
      renderProfile(data);
    } else if (data.type === "assessment") {
      renderAssessment(data);
    } else if (data.type === "rate_limited") {
      es.close();
      window.location.href = data.redirect || "/login?reason=limit";
    } else if (data.type === "done") {
      es.close();
    }
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
  renderStubs();
  if (window.ODIN_QUERY) startStream(window.ODIN_QUERY);
});
