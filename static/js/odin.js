// Odin — site-wide JS loaded on every page.
//
//   * Type-on for any [data-typewriter-text] element. Hero tagline uses it
//     for the opening "decrypt the public record." reveal; status-bar values
//     use it only on the profile page (where the bar reads as the active
//     terminal session line).
//
//   * First-input quota fade — when the user starts typing in the hero
//     search box, the line below it ("X of N free searches remaining…")
//     fades out. The original Odin design behavior, restored here.
//
//   * Konami code → code-rain easter egg. Press ↑↑↓↓←→←→BA outside of any
//     text input and ~90 columns of half-width katakana rain through the
//     viewport for ~6 seconds.

(() => {
  "use strict";

  const body = document.body;
  const prefersReducedMotion = window.matchMedia(
    "(prefers-reduced-motion: reduce)",
  ).matches;

  // ----- Type-on ------------------------------------------------------

  const typeonTimers = [];

  function applyTypeon() {
    const els = document.querySelectorAll("[data-typewriter-text]");
    if (els.length === 0) return;

    typeonTimers.forEach((t) => clearTimeout(t));
    typeonTimers.length = 0;
    els.forEach((el) => el.classList.remove("is-typing", "is-typed"));

    // Status bar values only type on the profile page; on other pages
    // where the bar appears (hero when signed in, dashboard, auth),
    // they render statically so the chrome doesn't keep re-animating.
    const isProfile = body.classList.contains("page-profile");
    const ordered = Array.from(els).filter((el) => {
      if (el.closest(".status-bar")) return isProfile;
      return true;
    });

    if (prefersReducedMotion) {
      ordered.forEach((el) => {
        el.textContent = el.dataset.typewriterText;
        el.classList.add("is-typed");
      });
      return;
    }

    ordered.forEach((el) => {
      el.textContent = "";
    });

    let cumulativeDelay = 150;
    ordered.forEach((el) => {
      const text = el.dataset.typewriterText;
      typeonTimers.push(
        setTimeout(() => {
          el.classList.add("is-typing");
          let i = 0;
          const tick = () => {
            if (i <= text.length) {
              el.textContent = text.slice(0, i);
              i++;
              typeonTimers.push(setTimeout(tick, 16 + Math.random() * 22));
            } else {
              el.classList.remove("is-typing");
              el.classList.add("is-typed");
            }
          };
          tick();
        }, cumulativeDelay),
      );
      cumulativeDelay += text.length * 30 + 220;
    });
  }

  // ----- First-input quota fade --------------------------------------

  function wireQuotaFade() {
    const input = document.querySelector(".search-form__input");
    const quota = document.querySelector(".hero__quota");
    if (!input || !quota) return;
    input.addEventListener("input", () => {
      if (input.value.length > 0 && !quota.classList.contains("is-hidden")) {
        quota.classList.add("is-hidden");
      }
    });
  }

  // ----- Code rain (Konami easter egg) -------------------------------

  function startRain() {
    document
      .querySelectorAll(".code-rain-overlay")
      .forEach((el) => el.remove());

    const overlay = document.createElement("div");
    overlay.className = "code-rain-overlay";
    overlay.setAttribute("aria-hidden", "true");

    const colCount = Math.min(96, Math.floor(window.innerWidth / 13));
    for (let c = 0; c < colCount; c++) {
      const col = document.createElement("div");
      col.className = "code-rain-overlay__col";
      col.style.left = ((c + 0.5) / colCount) * 100 + "%";
      col.style.animationDuration = (2.5 + Math.random() * 5) + "s";
      col.style.animationDelay = (Math.random() * 2.5) + "s";

      const len = 14 + Math.floor(Math.random() * 22);
      for (let i = 0; i < len; i++) {
        const glyph = document.createElement("span");
        glyph.className = "code-rain__glyph";
        // Half-width katakana — the Unicode block the film used.
        const code = 0xff65 + Math.floor(Math.random() * 60);
        glyph.textContent = String.fromCharCode(code);

        const fromEnd = len - 1 - i;
        if (fromEnd === 0) glyph.classList.add("code-rain__glyph--lead");
        else if (fromEnd <= 2) glyph.classList.add("code-rain__glyph--bright");
        else if (fromEnd <= 6) glyph.classList.add("code-rain__glyph--mid");
        else if (fromEnd <= 12) glyph.classList.add("code-rain__glyph--dim");
        else glyph.classList.add("code-rain__glyph--faint");

        const r = Math.random();
        if (r < 0.06) glyph.classList.add("code-rain__glyph--blue");
        else if (r < 0.14) glyph.classList.add("code-rain__glyph--deep");

        col.appendChild(glyph);
      }
      overlay.appendChild(col);
    }
    document.body.appendChild(overlay);

    setTimeout(() => {
      overlay.classList.add("is-fading");
      setTimeout(() => overlay.remove(), 700);
    }, 6000);
  }

  // ----- Banner dismiss -------------------------------------------------

  function wireBannerDismiss() {
    const form = document.querySelector(".disclosure-banner__form");
    if (!form) return;
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      fetch("/notice/dismiss", { method: "POST" }).finally(() => {
        const banner = document.getElementById("disclosure-banner");
        if (banner) banner.remove();
      });
    });
  }

  const KONAMI_SEQ = [
    "ArrowUp", "ArrowUp",
    "ArrowDown", "ArrowDown",
    "ArrowLeft", "ArrowRight",
    "ArrowLeft", "ArrowRight",
    "b", "a",
  ];
  let konamiIndex = 0;

  function wireKonami() {
    document.addEventListener("keydown", (e) => {
      const t = e.target;
      if (
        t &&
        (t.tagName === "INPUT" ||
          t.tagName === "TEXTAREA" ||
          t.isContentEditable)
      ) {
        return;
      }
      const key = e.key.length === 1 ? e.key.toLowerCase() : e.key;
      if (key === KONAMI_SEQ[konamiIndex]) {
        konamiIndex++;
        if (konamiIndex === KONAMI_SEQ.length) {
          startRain();
          konamiIndex = 0;
        }
      } else {
        konamiIndex = key === KONAMI_SEQ[0] ? 1 : 0;
      }
    });
  }

  // ----- Bootstrap ---------------------------------------------------

  function init() {
    applyTypeon();
    wireQuotaFade();
    wireKonami();
    wireBannerDismiss();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  // Exposed for profile.js so it can re-run type-on after it rewrites
  // the status bar (e.g. when reflowing on signed-in profile pages).
  // Keep the surface area minimal.
  window.odin = window.odin || {};
  window.odin.applyTypeon = applyTypeon;
  window.odin.startRain = startRain;
})();
