"""One-off script: generate static/og-image.png from a Playwright screenshot.

Run from the repo root:
    python scripts/generate_og_image.py

Playwright must be installed and browsers must be available (they are in the
dev environment via pyproject.toml). The resulting PNG is committed to the
repo so the web server can serve it as a static asset.
"""

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link rel="stylesheet"
        href="https://fonts.googleapis.com/css2?family=Orbitron:wght@700;900&display=swap" />
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      width: 1200px;
      height: 630px;
      background: #050505;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 28px;
    }
    .wordmark {
      font-family: 'Orbitron', sans-serif;
      font-weight: 900;
      font-size: 148px;
      letter-spacing: 0.15em;
      color: oklch(82% 0.22 155deg);
      text-shadow:
        0 0 24px oklch(92% 0.22 155deg / 0.9),
        0 0 72px oklch(82% 0.22 155deg / 0.6),
        0 0 140px oklch(82% 0.22 155deg / 0.35);
    }
    .tagline {
      font-family: 'Orbitron', sans-serif;
      font-weight: 700;
      font-size: 22px;
      letter-spacing: 0.28em;
      color: oklch(62% 0.15 150deg);
      text-transform: uppercase;
    }
  </style>
</head>
<body>
  <div class="wordmark">ODIN</div>
  <div class="tagline">Decode the digital domain</div>
</body>
</html>
"""

_OUT = Path(__file__).parent.parent / "static" / "og-image.png"


async def main() -> None:
    """Screenshot a minimal HTML page and save it as the OG image."""
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1200, "height": 630})
        await page.set_content(_HTML, wait_until="networkidle")
        await page.screenshot(
            path=str(_OUT),
            type="png",
            clip={"x": 0, "y": 0, "width": 1200, "height": 630},
        )
        await browser.close()
    print(f"Written: {_OUT}")


if __name__ == "__main__":
    asyncio.run(main())
