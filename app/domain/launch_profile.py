"""Launch profile: site + strict location + search filters (validated JSON)."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ROOT = Path(__file__).resolve().parents[2]
AREAS_PATH = ROOT / "config" / "areas.json"
# Default under data/ so Railway volume persists UI saves; override via LAUNCH_PATH.
DEFAULT_LAUNCH_PATH = ROOT / "data" / "config" / "launch.json"
EXAMPLE_LAUNCH_PATH = ROOT / "config" / "launch.example.json"

SiteName = Literal["rabota.by", "hh.ru"]

# Site ↔ country binding (HH family). Extend when adding sites to areas.json.
SITE_COUNTRY: dict[str, str] = {
    "rabota.by": "Беларусь",
    "hh.ru": "Россия",
}

HH_DEFAULT_QUERIES: list[str] = [
    "Python разработчик",
    "Python разработчик backend",
    "Python разработчик fastapi",
    "Python разработчик django",
    "Python разработчик middle",
    "Python разработчик developer",
    "Backend python",
    "Backend python developer",
    "Backend python django",
    "Backend python разработчик",
    "Backend python fastapi",
    "Python developer",
    "Python developer fastapi",
    "Python developer middle",
    "Python developer backend",
    "Python developer django",
    "Python develop",
]

# Soft defaults when keys are missing (file may be partial).
HH_LAUNCH_DEFAULTS: dict[str, Any] = {
    "site": "rabota.by",
    "location": {"country": "Беларусь", "city": "Минск", "strict": True},
    "queries": list(HH_DEFAULT_QUERIES),
    "require_remote_or_hybrid": True,
    "skip_gov": True,
    "require_python_keywords": True,
    "vacancy_limit": 30,
    "apply_limit": 30,
    "dry_run": False,
    "salary_min_usd": 2200,
    "salary_max_usd": 2800,
    "salary_strict": False,
    "level": "middle+",
    "schedule": {
        "enabled": True,
        "timezone": "Europe/Minsk",
        "times": ["00:00", "12:00"],
        "cron_job_rules": "1111",
        "email_report_after_run": True,
    },
}

# Strict text format for humans (parsed → JSON):
# site: rabota.by
# country: Беларусь
# city: Минск
# strict: true
# targets: rabota.by/Беларусь/Минск/true, hh.ru/Россия/Москва/true
# queries: python-разработчик, python-developer
# remote_or_hybrid: true
# skip_gov: true
# python_keywords: true
# vacancy_limit: 30
# apply_limit: 30
# dry_run: false
# salary_min_usd: 2200
# salary_max_usd: 2800
# salary_strict: false
# level: middle+
# schedule_enabled: true
# schedule_timezone: Europe/Minsk
# schedule_times: 00:00, 12:00
# cron_job_rules: 1111
# email_report_after_run: true

STRICT_TEXT_KEYS = {
    "site",
    "country",
    "city",
    "strict",
    "targets",
    "queries",
    "remote_or_hybrid",
    "skip_gov",
    "python_keywords",
    "vacancy_limit",
    "apply_limit",
    "dry_run",
    "salary_min_usd",
    "salary_max_usd",
    "salary_strict",
    "level",
    "schedule_enabled",
    "schedule_timezone",
    "schedule_times",
    "cron_job_rules",
    "email_report_after_run",
}


class LocationPref(BaseModel):
    country: str = Field(min_length=2, max_length=64)
    city: str = Field(min_length=2, max_length=64)
    strict: bool = True
    # resolved from areas.json
    area_id: str | None = None
    country_area_id: str | None = None
    city_aliases: list[str] = Field(default_factory=list)
    country_aliases: list[str] = Field(default_factory=list)


class SearchTarget(BaseModel):
    """One SERP target: site + location (country-wide when strict=false)."""

    site: SiteName
    location: LocationPref

    @model_validator(mode="after")
    def _resolve_and_bind(self) -> SearchTarget:
        resolved = resolve_location(self.location.country, self.location.city)
        self.location.area_id = resolved["area_id"]
        self.location.country_area_id = resolved["country_area_id"]
        self.location.city_aliases = resolved["city_aliases"]
        self.location.country_aliases = resolved["country_aliases"]
        self.location.country = resolved["country"]
        self.location.city = resolved["city"]
        expected = SITE_COUNTRY.get(self.site)
        if expected and resolved["country"] != expected:
            raise ValueError(
                f"Для site={self.site} локация должна быть в стране {expected!r} "
                f"(сейчас country={resolved['country']!r})"
            )
        return self

    @property
    def base_url(self) -> str:
        return site_base_url(self.site)

    @property
    def search_area(self) -> str:
        # strict city → city area; else country-wide for this target
        if self.location.strict and self.location.area_id:
            return self.location.area_id
        return self.location.country_area_id or self.location.area_id or ""


class SchedulePref(BaseModel):
    """
    Cron-like parse schedule stored in launch.json (editable from UI).

    cron_job_rules bitmask (4 chars, left→right):
      0: HH search, 1: HH apply, 2: LI vacancies, 3: LI network
    Example "1111" = all four; "1010" = HH search + LI vacancies only.
    """

    enabled: bool = True
    timezone: str = "Europe/Minsk"
    times: list[str] = Field(default_factory=lambda: ["00:00", "12:00"])
    cron_job_rules: str = "1111"
    email_report_after_run: bool = True

    @field_validator("timezone", mode="before")
    @classmethod
    def _norm_tz(cls, v: Any) -> str:
        s = str(v or "Europe/Minsk").strip() or "Europe/Minsk"
        return s

    @field_validator("times", mode="before")
    @classmethod
    def _norm_times(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            parts = re.split(r"[,;\s]+", v)
        elif isinstance(v, list):
            parts = v
        else:
            parts = ["00:00", "12:00"]
        out: list[str] = []
        seen: set[str] = set()
        for p in parts:
            token = str(p).strip()
            if not token:
                continue
            if ":" not in token and token.isdigit():
                token = f"{int(token):02d}:00"
            # Normalize HH:MM
            try:
                hs, ms = token.split(":", 1)
                hour = int(hs)
                minute = int(ms)
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    continue
                token = f"{hour:02d}:{minute:02d}"
            except ValueError:
                continue
            if token in seen:
                continue
            seen.add(token)
            out.append(token)
        return out or ["00:00", "12:00"]

    @field_validator("cron_job_rules", mode="before")
    @classmethod
    def _norm_rules(cls, v: Any) -> str:
        raw = str(v if v is not None else "1111").strip()
        bits = "".join(c for c in raw if c in "01")
        if not bits:
            bits = "1111"
        return (bits + "0000")[:4]

    def job_enabled(self, index: int) -> bool:
        rules = self.cron_job_rules or "0000"
        if index < 0 or index >= len(rules):
            return False
        return rules[index] == "1"


class LaunchProfile(BaseModel):
    """Параметры одного поискового прогона (файл launch.json)."""

    site: SiteName
    location: LocationPref
    # Multi-country: sequential SERP per target; shared queries/filters/vacancy_limit.
    # Empty → synthesized from site+location. Primary site/location mirror targets[0].
    targets: list[SearchTarget] = Field(default_factory=list)
    queries: list[str] = Field(min_length=1)
    require_remote_or_hybrid: bool = True
    skip_gov: bool = True
    require_python_keywords: bool = True
    # Max vacancies to find/parse in one search run (shown in UI as «до N»).
    vacancy_limit: int = Field(default=30, ge=1, le=100_000)
    # Max queued vacancies to apply in one apply run (all categories HIGH→LOW).
    apply_limit: int = Field(default=30, ge=1, le=100_000)
    dry_run: bool = False
    # Legend: $2200–2800 Middle+
    salary_min_usd: int | None = Field(default=2200, ge=0, le=50_000)
    salary_max_usd: int | None = Field(default=2800, ge=0, le=50_000)
    salary_strict: bool = False  # true → filter out clearly below min
    level: str = Field(default="middle+")
    schedule: SchedulePref = Field(default_factory=SchedulePref)

    @model_validator(mode="before")
    @classmethod
    def _normalize_targets_input(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        raw = dict(data)
        targets = raw.get("targets")
        if isinstance(targets, str):
            targets = parse_targets_text(targets, default_strict=True)
            raw["targets"] = targets
        if isinstance(targets, list) and targets:
            first = targets[0]
            if isinstance(first, SearchTarget):
                if "site" not in raw:
                    raw["site"] = first.site
                if "location" not in raw:
                    raw["location"] = first.location
            elif isinstance(first, dict):
                if "site" not in raw and first.get("site"):
                    raw["site"] = first["site"]
                if "location" not in raw and first.get("location"):
                    raw["location"] = first["location"]
                elif "location" not in raw and (
                    "country" in first or "city" in first
                ):
                    raw["location"] = {
                        "country": first.get("country", ""),
                        "city": first.get("city", ""),
                        "strict": first.get("strict", True),
                    }
                    raw["targets"] = [
                        (
                            t
                            if not isinstance(t, dict)
                            else {
                                "site": t.get("site"),
                                "location": t.get("location")
                                or {
                                    "country": t.get("country"),
                                    "city": t.get("city"),
                                    "strict": t.get("strict", True),
                                },
                            }
                        )
                        for t in targets
                    ]
        elif raw.get("site") and (
            raw.get("location")
            or raw.get("country")
            or raw.get("city")
        ):
            loc = raw.get("location")
            if not isinstance(loc, dict):
                loc = {
                    "country": raw.get("country", HH_LAUNCH_DEFAULTS["location"]["country"]),
                    "city": raw.get("city", HH_LAUNCH_DEFAULTS["location"]["city"]),
                    "strict": raw.get("strict", True),
                }
            raw["targets"] = [{"site": raw["site"], "location": loc}]
        return raw

    @field_validator("queries", mode="before")
    @classmethod
    def _split_queries(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            parts = re.split(r"[,;\n]+", v)
        elif isinstance(v, list):
            parts = v
        else:
            raise ValueError("queries must be list or comma-separated string")
        out: list[str] = []
        seen: set[str] = set()
        for p in parts:
            q = str(p).strip()
            if not q:
                continue
            key = q.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(q)
        if not out:
            raise ValueError("queries: нужен хотя бы один поисковый запрос")
        return out

    @field_validator("level", mode="before")
    @classmethod
    def _norm_level(cls, v: Any) -> str:
        s = str(v or "middle+").strip().casefold().replace(" ", "")
        aliases = {
            "middle+": "middle+",
            "middleplus": "middle+",
            "мидл+": "middle+",
            "middle": "middle",
            "мидл": "middle",
            "senior": "senior",
            "junior": "junior",
        }
        return aliases.get(s, s)

    @model_validator(mode="after")
    def _sync_targets_and_primary(self) -> LaunchProfile:
        if not self.targets:
            self.targets = [
                SearchTarget(site=self.site, location=self.location)
            ]
        # Primary mirrors first target (login / meta / backward compat).
        primary = self.targets[0]
        self.site = primary.site
        self.location = primary.location
        if (
            self.salary_min_usd is not None
            and self.salary_max_usd is not None
            and self.salary_min_usd > self.salary_max_usd
        ):
            raise ValueError("salary_min_usd не может быть больше salary_max_usd")
        return self

    @property
    def base_url(self) -> str:
        return site_base_url(self.site)

    @property
    def search_area(self) -> str:
        # Primary target area (compat). Prefer iter_targets() in search loop.
        if self.location.strict and self.location.area_id:
            return self.location.area_id
        return self.location.country_area_id or self.location.area_id or ""

    def iter_targets(self) -> list[SearchTarget]:
        return list(self.targets) if self.targets else [
            SearchTarget(site=self.site, location=self.location)
        ]

    def to_public_dict(self) -> dict[str, Any]:
        return self.model_dump()


@lru_cache
def load_areas_catalog() -> dict[str, Any]:
    if not AREAS_PATH.exists():
        return {"sites": {}, "locations": []}
    return json.loads(AREAS_PATH.read_text(encoding="utf-8"))


def site_base_url(site: str) -> str:
    cat = load_areas_catalog()
    entry = (cat.get("sites") or {}).get(site) or {}
    return str(entry.get("base_url") or f"https://{site}")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().casefold().replace("ё", "е"))


def _alias_in_text(alias: str, blob: str) -> bool:
    """Substring / stem match so «Гомель» ловит «Гомеля»."""
    a = _norm(alias)
    if not a or len(a) < 3:
        return False
    if a in blob:
        return True
    stem = a.rstrip("ьъ")
    if len(stem) >= 4 and re.search(rf"{re.escape(stem)}\w*", blob):
        return True
    return False


def resolve_location(country: str, city: str) -> dict[str, Any]:
    cat = load_areas_catalog()
    c_norm = _norm(country)
    city_norm = _norm(city)
    for loc in cat.get("locations") or []:
        aliases = [_norm(loc.get("country", ""))] + [
            _norm(a) for a in (loc.get("country_aliases") or [])
        ]
        if c_norm not in aliases:
            continue
        for city_row in loc.get("cities") or []:
            city_aliases = [_norm(city_row.get("city", ""))] + [
                _norm(a) for a in (city_row.get("aliases") or [])
            ]
            if city_norm in city_aliases:
                return {
                    "country": loc["country"],
                    "city": city_row["city"],
                    "area_id": str(city_row["area_id"]),
                    "country_area_id": str(loc["country_area_id"]),
                    "city_aliases": [city_row["city"], *(city_row.get("aliases") or [])],
                    "country_aliases": [
                        loc["country"],
                        *(loc.get("country_aliases") or []),
                    ],
                }
        known = ", ".join(c["city"] for c in (loc.get("cities") or []))
        raise ValueError(
            f"Город {city!r} не найден в стране {loc['country']}. "
            f"Доступно: {known}"
        )
    countries = ", ".join(loc["country"] for loc in (cat.get("locations") or []))
    raise ValueError(
        f"Страна {country!r} не поддерживается. Доступно: {countries}"
    )


def parse_bool(raw: str) -> bool:
    v = raw.strip().casefold()
    if v in ("1", "true", "yes", "y", "да", "on"):
        return True
    if v in ("0", "false", "no", "n", "нет", "off"):
        return False
    raise ValueError(f"Ожидался bool, получено: {raw!r}")


def parse_targets_text(
    text: str,
    *,
    default_strict: bool = True,
) -> list[dict[str, Any]]:
    """
    Parse targets DSL:
      rabota.by/Беларусь/Минск, hh.ru/Россия/Москва/false
    Separators between targets: comma or semicolon.
    Parts: site/country/city[/strict]
    """
    out: list[dict[str, Any]] = []
    chunks = re.split(r"[,;]+", text or "")
    for i, chunk in enumerate(chunks, start=1):
        token = chunk.strip()
        if not token:
            continue
        parts = [p.strip() for p in token.split("/")]
        if len(parts) < 3:
            raise ValueError(
                f"targets[{i}]: нужен формат site/country/city[/strict], получено {token!r}"
            )
        if len(parts) > 4:
            raise ValueError(
                f"targets[{i}]: слишком много частей в {token!r} "
                "(ожидалось site/country/city[/strict])"
            )
        site = parts[0].casefold()
        country, city = parts[1], parts[2]
        strict = default_strict
        if len(parts) == 4:
            strict = parse_bool(parts[3])
        if site not in SITE_COUNTRY:
            known = ", ".join(SITE_COUNTRY)
            raise ValueError(
                f"targets[{i}]: неизвестный site {site!r}. Допустимо: {known}"
            )
        out.append(
            {
                "site": site,
                "location": {
                    "country": country,
                    "city": city,
                    "strict": strict,
                },
            }
        )
    if not out:
        raise ValueError("targets: нужен хотя бы один site/country/city")
    return out


def targets_to_strict_text(targets: list[SearchTarget]) -> str:
    parts: list[str] = []
    for t in targets:
        loc = t.location
        parts.append(
            f"{t.site}/{loc.country}/{loc.city}/{str(loc.strict).lower()}"
        )
    return ", ".join(parts)


def parse_strict_text(text: str) -> dict[str, Any]:
    """
    Парсит строгий key: value формат в сырой dict (до LaunchProfile).
    """
    raw: dict[str, Any] = {}
    for i, line in enumerate((text or "").splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(f"Строка {i}: нужен формат key: value → {line!r}")
        key, val = line.split(":", 1)
        key = key.strip().casefold()
        val = val.strip()
        if key not in STRICT_TEXT_KEYS:
            raise ValueError(
                f"Строка {i}: неизвестный ключ {key!r}. "
                f"Допустимо: {', '.join(sorted(STRICT_TEXT_KEYS))}"
            )
        raw[key] = val

    default_strict = parse_bool(raw["strict"]) if "strict" in raw else True
    targets_raw: list[dict[str, Any]] | None = None
    if "targets" in raw:
        targets_raw = parse_targets_text(
            raw["targets"], default_strict=default_strict
        )

    has_primary = "site" in raw and "country" in raw and "city" in raw
    if not targets_raw and not has_primary:
        raise ValueError(
            "Не хватает обязательных полей: либо site+country+city, либо targets; "
            "и всегда queries"
        )
    if "queries" not in raw:
        raise ValueError("Не хватает обязательных полей: queries")

    if targets_raw:
        primary = targets_raw[0]
        site = str(primary["site"]).casefold()
        location = dict(primary["location"])
    else:
        site = raw["site"].casefold()
        location = {
            "country": raw["country"],
            "city": raw["city"],
            "strict": default_strict,
        }
        targets_raw = [{"site": site, "location": location}]

    # Classic site/country/city override primary when both present (explicit single fields).
    if has_primary and "targets" not in raw:
        site = raw["site"].casefold()
        location = {
            "country": raw["country"],
            "city": raw["city"],
            "strict": default_strict,
        }
        targets_raw = [{"site": site, "location": location}]
    elif has_primary and "targets" in raw:
        # Keep targets list; site/country/city in DSL are informational / first-target hints.
        pass

    payload: dict[str, Any] = {
        "site": site,
        "location": location,
        "targets": targets_raw,
        "queries": raw["queries"],
        "require_remote_or_hybrid": (
            parse_bool(raw["remote_or_hybrid"])
            if "remote_or_hybrid" in raw
            else True
        ),
        "skip_gov": parse_bool(raw["skip_gov"]) if "skip_gov" in raw else True,
        "require_python_keywords": (
            parse_bool(raw["python_keywords"])
            if "python_keywords" in raw
            else True
        ),
    }
    if "vacancy_limit" in raw:
        payload["vacancy_limit"] = int(raw["vacancy_limit"])
    if "apply_limit" in raw:
        payload["apply_limit"] = int(raw["apply_limit"])
    if "dry_run" in raw:
        payload["dry_run"] = parse_bool(raw["dry_run"])
    if "salary_min_usd" in raw:
        payload["salary_min_usd"] = int(re.sub(r"[^\d]", "", raw["salary_min_usd"]) or "0")
    if "salary_max_usd" in raw:
        payload["salary_max_usd"] = int(re.sub(r"[^\d]", "", raw["salary_max_usd"]) or "0")
    if "salary_strict" in raw:
        payload["salary_strict"] = parse_bool(raw["salary_strict"])
    if "level" in raw:
        payload["level"] = raw["level"]

    schedule: dict[str, Any] = {}
    if "schedule_enabled" in raw:
        schedule["enabled"] = parse_bool(raw["schedule_enabled"])
    if "schedule_timezone" in raw:
        schedule["timezone"] = raw["schedule_timezone"]
    if "schedule_times" in raw:
        schedule["times"] = raw["schedule_times"]
    if "cron_job_rules" in raw:
        schedule["cron_job_rules"] = raw["cron_job_rules"]
    if "email_report_after_run" in raw:
        schedule["email_report_after_run"] = parse_bool(raw["email_report_after_run"])
    if schedule:
        payload["schedule"] = schedule
    return payload


def validate_launch_dict(data: dict[str, Any]) -> LaunchProfile:
    return LaunchProfile.model_validate(data)


def parse_and_validate_text(text: str) -> LaunchProfile:
    return validate_launch_dict(parse_strict_text(text))


def launch_to_strict_text(profile: LaunchProfile) -> str:
    loc = profile.location
    sched = profile.schedule
    queries = ", ".join(profile.queries)
    times = ", ".join(sched.times)
    targets = profile.iter_targets()
    lines = [
        f"site: {profile.site}",
        f"country: {loc.country}",
        f"city: {loc.city}",
        f"strict: {str(loc.strict).lower()}",
    ]
    if len(targets) > 1:
        lines.append(f"targets: {targets_to_strict_text(targets)}")
    lines.extend(
        [
            f"queries: {queries}",
            f"remote_or_hybrid: {str(profile.require_remote_or_hybrid).lower()}",
            f"skip_gov: {str(profile.skip_gov).lower()}",
            f"python_keywords: {str(profile.require_python_keywords).lower()}",
            f"vacancy_limit: {profile.vacancy_limit}",
            f"apply_limit: {profile.apply_limit}",
            f"dry_run: {str(profile.dry_run).lower()}",
            f"salary_min_usd: {profile.salary_min_usd if profile.salary_min_usd is not None else ''}",
            f"salary_max_usd: {profile.salary_max_usd if profile.salary_max_usd is not None else ''}",
            f"salary_strict: {str(profile.salary_strict).lower()}",
            f"level: {profile.level}",
            f"schedule_enabled: {str(sched.enabled).lower()}",
            f"schedule_timezone: {sched.timezone}",
            f"schedule_times: {times}",
            f"cron_job_rules: {sched.cron_job_rules}",
            f"email_report_after_run: {str(sched.email_report_after_run).lower()}",
            "",
        ]
    )
    return "\n".join(lines)


def load_launch_profile(path: Path | None = None) -> LaunchProfile | None:
    """Load launch profile; on missing/partial file apply soft defaults."""
    profile, _ = load_launch_profile_with_notes(path)
    return profile


def load_launch_profile_with_notes(
    path: Path | None = None,
) -> tuple[LaunchProfile | None, list[str]]:
    """
    Load + soft-merge defaults. Returns (profile, notifications).
    Notifications are for UI when a default was applied because a key was missing.
    """
    from app.domain.config_defaults import deep_merge_defaults

    p = path or DEFAULT_LAUNCH_PATH
    notes: list[str] = []
    raw: dict[str, Any] | None = None
    if p.exists():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            notes.append(f"launch.json unreadable ({e}); using defaults")
            raw = None
    elif EXAMPLE_LAUNCH_PATH.exists() and path is None:
        try:
            raw = json.loads(EXAMPLE_LAUNCH_PATH.read_text(encoding="utf-8"))
            notes.append(
                "using config/launch.example.json because config/launch.json missing"
            )
        except (OSError, json.JSONDecodeError):
            raw = None

    if raw is None and not notes:
        notes.append("using launch defaults because config/launch.json missing")

    # Normalize flat location keys if someone saved strict-text style JSON
    if raw and "location" not in raw and ("country" in raw or "city" in raw):
        raw = {
            **{k: v for k, v in raw.items() if k not in ("country", "city", "strict")},
            "location": {
                "country": raw.get("country", HH_LAUNCH_DEFAULTS["location"]["country"]),
                "city": raw.get("city", HH_LAUNCH_DEFAULTS["location"]["city"]),
                "strict": raw.get("strict", True),
            },
        }

    merged, merge_notes = deep_merge_defaults(raw, HH_LAUNCH_DEFAULTS, prefix="launch")
    notes.extend(merge_notes)
    # Legacy: apply_limit used to cap search; mirror it when vacancy_limit absent.
    if (
        isinstance(raw, dict)
        and "vacancy_limit" not in raw
        and "apply_limit" in raw
        and "apply_limit" in merged
    ):
        merged["vacancy_limit"] = int(merged["apply_limit"])
        notes.append(
            "launch.vacancy_limit ← apply_limit (legacy; set vacancy_limit explicitly)"
        )
    try:
        return validate_launch_dict(merged), notes
    except Exception as e:
        notes.append(f"launch validation failed ({e}); retrying pure defaults")
        try:
            return validate_launch_dict(dict(HH_LAUNCH_DEFAULTS)), notes
        except Exception:
            return None, notes


def save_launch_profile(profile: LaunchProfile, path: Path | None = None) -> Path:
    p = path or DEFAULT_LAUNCH_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(profile.model_dump(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return p


def location_match_score(
    title: str,
    description: str,
    location: LocationPref,
) -> tuple[str, float]:
    """
    Returns (code, weight contribution hint).
    location_hit → positive, location_miss → negative when strict.
    """
    blob = _norm(f"{title}\n{description}")
    city_hit = any(_alias_in_text(a, blob) for a in location.city_aliases if a)
    country_hit = any(_alias_in_text(a, blob) for a in location.country_aliases if a)

    # other known cities from same catalog → mismatch if different city mentioned
    other_city = False
    cat = load_areas_catalog()
    for loc in cat.get("locations") or []:
        for city_row in loc.get("cities") or []:
            name = city_row.get("city") or ""
            if _norm(name) == _norm(location.city):
                continue
            aliases = [name, *(city_row.get("aliases") or [])]
            if any(_alias_in_text(a, blob) for a in aliases):
                other_city = True
                break
        if other_city:
            break

    if location.strict:
        if city_hit:
            return "location_city_hit", 0.55
        if other_city:
            return "location_other_city", -0.75
        if country_hit:
            return "location_country_only", 0.15
        # no location text — search area already constrained; mild neutral-positive
        return "location_area_assumed", 0.08
    if city_hit:
        return "location_city_hit", 0.4
    if country_hit:
        return "location_country_only", 0.1
    return "location_unspecified", 0.0


# Approximate FX for scoring (enough for fit, not accounting)
_FX_TO_USD = {
    "usd": 1.0,
    "$": 1.0,
    "dollar": 1.0,
    "eur": 1.08,
    "€": 1.08,
    "byn": 0.30,
    "бр": 0.30,
    "руб": 0.011,
    "rub": 0.011,
    "₽": 0.011,
}

_SALARY_RE = re.compile(
    r"(?P<from>от\s*)?(?P<a>\d[\d\s]{2,6})(?:\s*[-–—]\s*(?P<b>\d[\d\s]{2,6}))?"
    r"\s*(?P<cur>usd|\$|eur|€|byn|бр|руб(?:лей)?|rub|₽)?",
    re.IGNORECASE,
)


def _parse_num(raw: str) -> int | None:
    digits = re.sub(r"\s+", "", raw or "")
    if not digits.isdigit():
        return None
    return int(digits)


def extract_salary_usd(text: str) -> tuple[int | None, int | None]:
    """Best-effort (min, max) monthly USD from vacancy text."""
    blob = text or ""
    best: tuple[int, int] | None = None
    for m in _SALARY_RE.finditer(blob):
        a = _parse_num(m.group("a") or "")
        b = _parse_num(m.group("b") or "") if m.group("b") else None
        if a is None:
            continue
        cur_raw = (m.group("cur") or "").casefold()
        # skip tiny numbers without currency (years of experience etc.)
        if not cur_raw and a < 500:
            continue
        rate = _FX_TO_USD.get(cur_raw, 1.0 if cur_raw in ("usd", "$") or not cur_raw else None)
        if rate is None:
            continue
        # BYN/RUB without currency often look like 2500 BYN — if no cur and 1000..9999 on rabota, treat as BYN-ish when site BY? Keep USD default for bare large nums.
        if not cur_raw and 800 <= a <= 6000:
            rate = 1.0  # assume USD for international remote ads
        lo = int(a * rate)
        hi = int((b or a) * rate)
        if lo > hi:
            lo, hi = hi, lo
        if best is None or (hi - lo) > (best[1] - best[0]):
            best = (lo, hi)
    if not best:
        return None, None
    return best


def salary_match_score(
    title: str,
    description: str,
    *,
    salary_min_usd: int | None,
    salary_max_usd: int | None,
) -> tuple[str, float]:
    """Compare vacancy salary band to Legend/launch вилка."""
    if salary_min_usd is None and salary_max_usd is None:
        return "salary_prefs_off", 0.0
    lo, hi = extract_salary_usd(f"{title}\n{description}")
    if lo is None or hi is None:
        return "salary_unknown", 0.0
    pref_lo = salary_min_usd if salary_min_usd is not None else 0
    pref_hi = salary_max_usd if salary_max_usd is not None else 10**9
    # overlap?
    if hi < pref_lo:
        # clearly below
        gap = pref_lo - hi
        w = -0.85 if gap > 800 else -0.55
        return "salary_below", w
    if lo > pref_hi:
        # above max — still ok-ish for candidate
        return "salary_above", 0.25
    # overlap with preferred band
    return "salary_in_range", 0.65


def level_match_score(title: str, description: str, level: str) -> tuple[str, float]:
    blob = _norm(f"{title}\n{description}")
    lvl = (level or "middle+").casefold()
    if "junior" in blob and "middle" not in blob and lvl.startswith("middle"):
        return "level_junior_mismatch", -0.55
    if re.search(r"\blead\b|тимлид|team\s*lead", blob) and "middle" in lvl:
        return "level_lead_heavy", -0.25
    if "middle" in lvl and (
        "middle" in blob or "мидл" in blob or "middle+" in blob or "middle +" in blob
    ):
        return "level_middle_hit", 0.45
    if "senior" in blob and "middle" in lvl:
        return "level_senior_ok", 0.15
    return "level_unspecified", 0.0
