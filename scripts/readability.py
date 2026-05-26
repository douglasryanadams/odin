"""Report the reading level of the project's Markdown prose.

Strips code, tables, and YAML frontmatter from each Markdown file, then scores
the remaining prose with textstat. The target is a high-school reading level:
Flesch-Kincaid grade 12 or lower and Flesch Reading Ease 50 or higher. The
check is advisory; it prints a report and always exits zero.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import textstat

MAX_GRADE = 12.0
MIN_EASE = 50.0

_EXCLUDED_DIRS = {"node_modules", ".git", ".ruff_cache", ".pytest_cache", ".venv"}
_EXCLUDED_FILES = {".notes.md"}

_FRONTMATTER = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)
_FENCED_CODE = re.compile(r"```.*?```", re.DOTALL)
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_INLINE_CODE = re.compile(r"`[^`]*`")
_HTML_TAG = re.compile(r"<[^>]+>")
_HEADING = re.compile(r"^#{1,6}\s+")
_BULLET = re.compile(r"^[-*+]\s+")
_NUMBERED = re.compile(r"^\d+\.\s+")
_BLOCKQUOTE = re.compile(r"^>\s?")


@dataclass(frozen=True)
class Readability:
    """Flesch readability scores for a piece of prose."""

    grade: float
    ease: float


def _is_table_line(line: str) -> bool:
    """Return True for a Markdown table row or divider."""
    return line.startswith("|") or set(line) <= {"|", "-", ":", " "}


def strip_to_prose(markdown: str) -> str:
    """Reduce Markdown to plain prose so syntax does not skew the score."""
    text = _FRONTMATTER.sub("", markdown)
    text = _FENCED_CODE.sub(" ", text)
    text = _IMAGE.sub(" ", text)
    text = _LINK.sub(r"\1", text)
    text = _INLINE_CODE.sub(" ", text)
    text = _HTML_TAG.sub(" ", text)
    kept: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or _is_table_line(line):
            continue
        line = _HEADING.sub("", line)
        line = _BULLET.sub("", line)
        line = _NUMBERED.sub("", line)
        line = _BLOCKQUOTE.sub("", line)
        line = line.replace("**", "").replace("*", "").replace("_", "")
        kept.append(line)
    return " ".join(kept)


def score(prose: str) -> Readability:
    """Score prose with textstat's Flesch metrics."""
    return Readability(
        grade=textstat.flesch_kincaid_grade(prose),
        ease=textstat.flesch_reading_ease(prose),
    )


def passes(scores: Readability, max_grade: float = MAX_GRADE, min_ease: float = MIN_EASE) -> bool:
    """Return True when prose meets the high-school target on both metrics."""
    return scores.grade <= max_grade and scores.ease >= min_ease


def iter_markdown_files(root: Path) -> list[Path]:
    """List Markdown files under root, skipping caches and scratch files."""
    return [
        path
        for path in sorted(root.rglob("*.md"))
        if not _EXCLUDED_DIRS.intersection(path.parts) and path.name not in _EXCLUDED_FILES
    ]


def main() -> None:
    """Print a readability report for every Markdown file in the repo."""
    root = Path.cwd()
    scored = 0
    failures = 0
    for path in iter_markdown_files(root):
        prose = strip_to_prose(path.read_text(encoding="utf-8"))
        if not prose.strip():
            continue
        scored += 1
        scores = score(prose)
        ok = passes(scores)
        if not ok:
            failures += 1
        flag = "PASS" if ok else "FAIL"
        rel = path.relative_to(root)
        print(f"{flag}  grade {scores.grade:5.1f}  ease {scores.ease:6.1f}  {rel}")
    summary = (
        f"\n{scored - failures}/{scored} files within target "
        f"(grade <= {MAX_GRADE:.0f}, ease >= {MIN_EASE:.0f})."
    )
    print(summary)


if __name__ == "__main__":
    main()
