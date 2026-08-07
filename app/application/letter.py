"""Cover letter helpers + human-like rate limiter.

LETTER_PATH may point to a single .txt file or a directory of .txt templates.
LETTER_STYLE selects a file stem (e.g. impact) or rotate (default).

Template syntax:
  {A|B}                 — random variant
  {company}, {title}    — named fields (vacancy_name aliases title)
  {{company}}           — same as {company}
  {{#company}}...{{/company}} — optional block; dropped if value empty
  %(vacancy_name)s      — legacy title placeholder

Missing named values never render as "None": optional blocks are removed,
and any remaining sentence that still contains an unresolved named
placeholder is stripped.
"""

from __future__ import annotations

import random
import re
import time
import zlib
from pathlib import Path

_OPTIONAL_BLOCK = re.compile(r"\{\{#(\w+)\}\}(.*?)\{\{/\1\}\}", re.DOTALL)
_NAMED_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
_CHOICE = re.compile(r"\{([^{}|]+\|[^{}]*)\}")
_NAMED_KEYS = frozenset({"company", "title", "vacancy_name"})
_EMPTY_MARKERS = frozenset({"", "none", "null", "nil", "n/a", "-"})

_DEFAULT_LETTER = (
    "{Здравствуйте|Добрый день}!\n\n"
    "Меня заинтересовала вакансия %(vacancy_name)s. "
    "Кратко о себе: ответственный, быстро включаюсь в задачи.\n\n"
    "Буду рад обратной связи.\n\n"
    "С уважением,\n"
    "Тимофей"
)


def _clean_value(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in _EMPTY_MARKERS:
        return ""
    return text


def _values(
    title: str = "",
    company: str = "",
    vacancy_name: str = "",
) -> dict[str, str]:
    resolved_title = _clean_value(title) or _clean_value(vacancy_name)
    return {
        "title": resolved_title,
        "vacancy_name": resolved_title,
        "company": _clean_value(company),
    }


def _substitute_named(text: str, key: str, value: str) -> str:
    """Replace {{key}} then {key} so double-brace forms do not leave '{value}'."""
    if not value:
        return text
    text = text.replace("{{" + key + "}}", value)
    return text.replace("{" + key + "}", value)


def _expand_optional_blocks(template: str, values: dict[str, str]) -> str:
    text = template
    for _ in range(8):
        def repl(m: re.Match[str]) -> str:
            key, body = m.group(1), m.group(2)
            val = values.get(key, "").strip()
            if not val:
                return ""
            return _substitute_named(body, key, val)

        updated = _OPTIONAL_BLOCK.sub(repl, text)
        if updated == text:
            break
        text = updated
    return text


def _has_unresolved_named(fragment: str) -> bool:
    for match in _NAMED_PLACEHOLDER.finditer(fragment):
        if match.group(1) in _NAMED_KEYS:
            return True
    return False


def _strip_unresolved_placeholder_clauses(text: str) -> str:
    """Drop sentences/lines that still contain unresolved {company}/{title}/…"""
    out_lines: list[str] = []
    for line in text.splitlines():
        if not _has_unresolved_named(line):
            out_lines.append(line)
            continue
        parts = re.split(r"(?<=[.!?…])\s+", line)
        kept = [p for p in parts if p and not _has_unresolved_named(p)]
        if kept:
            out_lines.append(" ".join(kept))
    return "\n".join(out_lines)


def _cleanup_letter(text: str) -> str:
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    # Guard against literal None leaking from bad callers/templates.
    text = re.sub(r"\bNone\b", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def render_letter(
    template: str,
    vacancy_name: str = "",
    *,
    title: str = "",
    company: str = "",
) -> str:
    """Render a cover letter template with safe missing-data handling."""
    values = _values(title=title, company=company, vacancy_name=vacancy_name)
    text = _expand_optional_blocks(template, values)

    # Legacy printf-style placeholder.
    legacy_title = values["vacancy_name"] or "вашу вакансию"
    text = text.replace("%(vacancy_name)s", legacy_title)

    for key, val in values.items():
        if val:
            text = _substitute_named(text, key, val)

    text = _strip_unresolved_placeholder_clauses(text)

    def pick(m: re.Match[str]) -> str:
        return random.choice(m.group(1).split("|")).strip()

    text = _CHOICE.sub(pick, text)
    return _cleanup_letter(text)


def resolve_letter_files(path: str | Path | None) -> list[Path]:
    """Return template files for LETTER_PATH (file or directory of *.txt)."""
    if not path:
        return []
    p = Path(path)
    if p.is_dir():
        return sorted(p.glob("*.txt"))
    if p.is_file():
        return [p]
    return []


def load_letter_templates(path: str | Path | None) -> list[tuple[str, str]]:
    """Load templates as (stem, text). Falls back to a built-in stub."""
    files = resolve_letter_files(path)
    out: list[tuple[str, str]] = []
    for file in files:
        raw = file.read_text(encoding="utf-8").strip()
        if raw:
            out.append((file.stem, raw))
    return out or [("default", _DEFAULT_LETTER)]


def load_letters(path: str | Path | None) -> list[str]:
    """Load one or more letter template bodies."""
    return [text for _, text in load_letter_templates(path)]


def pick_letter(
    templates: list[str] | list[tuple[str, str]],
    *,
    style: str = "rotate",
    seed: str = "",
) -> str:
    """Pick a template by LETTER_STYLE or rotate (stable when seed is set)."""
    pairs: list[tuple[str, str]]
    if templates and isinstance(templates[0], tuple):
        pairs = list(templates)  # type: ignore[arg-type]
    else:
        pairs = [(f"style_{i + 1}", t) for i, t in enumerate(templates)]  # type: ignore[arg-type]

    if not pairs:
        return _DEFAULT_LETTER

    style_key = (style or "rotate").strip().lower()
    if style_key and style_key not in {"rotate", "random", "any"}:
        for name, text in pairs:
            stem = name.lower()
            if style_key == stem or style_key in stem:
                return text

    if len(pairs) == 1:
        return pairs[0][1]

    if seed:
        idx = zlib.adler32(seed.encode("utf-8")) % len(pairs)
        return pairs[idx][1]
    return random.choice(pairs)[1]


def load_letter(path: str | Path | None) -> str:
    """Load a single template (first file if LETTER_PATH is a directory)."""
    return load_letters(path)[0]


class RateLimiter:
    def __init__(self, min_interval: float, jitter: float = 0.35) -> None:
        self.min_interval = min_interval
        self.jitter = jitter
        self._last = 0.0

    def wait(self, extra: float = 0.0) -> float:
        now = time.monotonic()
        delay = max(
            0.3,
            (self.min_interval + extra)
            * (1.0 + random.uniform(-self.jitter, self.jitter)),
        )
        sleep_for = delay - (now - self._last)
        if sleep_for > 0:
            time.sleep(sleep_for)
        self._last = time.monotonic()
        return max(0.0, sleep_for)
