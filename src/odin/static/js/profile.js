// Odin profile page — SSE handler + card rendering.

const STUB_DATA = true;

const STAGES = ["categorized", "queries", "searching", "fetching", "profile"];

const CATEGORY_ICONS = {
  person: "fa-user",
  place: "fa-location-dot",
  event: "fa-calendar",
  other: "fa-circle-nodes",
};

const STUB_SOURCES = [
  { domain: "wikipedia.org", snippet: "Encyclopedic biography and career overview.", confidence: 92 },
  { domain: "britannica.com", snippet: "Curated biographical entry with citations.", confidence: 88 },
  { domain: "github.com", snippet: "Public repositories and contribution graph.", confidence: 74 },
];

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
  if (hl) renderHighlights(hl, data.highlights);
  if (ll) renderHighlights(ll, data.lowlights);
  if (tl) renderTimeline(tl, data.timeline);
  completeProgress();
  const strip = $("progress-strip");
  if (strip) strip.hidden = true;
}

function renderStubSources() {
  const list = document.querySelector("#card-sources .sources-list");
  if (!list) return;
  list.replaceChildren();
  STUB_SOURCES.forEach((src) => {
    const li = el("li", "source-item");
    li.appendChild(el("span", "source-item__favicon", src.domain.charAt(0).toUpperCase()));
    const body = el("div", "source-item__body");
    body.appendChild(el("span", "source-item__domain mono", src.domain));
    body.appendChild(el("p", "source-item__snippet muted", src.snippet));
    li.appendChild(body);
    li.appendChild(el("span", "source-item__confidence mono", `${src.confidence}%`));
    list.appendChild(li);
  });
}

function renderStubGauges() {
  const wrap = document.querySelector("#card-sentiment .gauges");
  if (!wrap) return;
  wrap.replaceChildren();
  wrap.appendChild(buildGauge("Profile confidence", 78, "gauge--confidence"));
  wrap.appendChild(buildSentimentGauge("Public sentiment", 0.32));
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

function buildSentimentGauge(label, position) {
  const wrap = el("div", "gauge gauge--sentiment");
  const top = el("div", "gauge__head");
  top.appendChild(el("span", "gauge__label", label));
  const value = position > 0 ? `+${(position * 100).toFixed(0)}` : `${(position * 100).toFixed(0)}`;
  top.appendChild(el("span", "gauge__value mono", value));
  wrap.appendChild(top);
  const track = el("div", "gauge__track gauge__track--diverging");
  const marker = el("span", "gauge__marker");
  marker.style.left = `${50 + position * 50}%`;
  track.appendChild(marker);
  wrap.appendChild(track);
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
  renderStubSources();
  renderStubGauges();
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
