"""Multi-label baseline: точные цитаты explicit, отдельные гипотезы inferred."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

import yaml

UNKNOWN = "insufficient_data"
DEFAULT_CATALOG = Path(__file__).with_name("needs_catalog.yaml")


@lru_cache(maxsize=8)
def _catalog_text(text: str) -> dict:
    result = yaml.safe_load(text)
    if not result.get("categories") or not result.get("version"):
        raise ValueError("Каталог должен содержать version и categories")
    for scenario in result.get("scenarios", []):
        if set(scenario["needs"]) - set(result["categories"]):
            raise ValueError("Неизвестная категория в сценарии")
    result["model_version"] = (
        result["version"] + "-" + hashlib.sha256(text.encode()).hexdigest()[:8]
    )
    return result


def load_catalog(path: Path | str | None = None) -> dict:
    return _catalog_text(Path(path or DEFAULT_CATALOG).read_text(encoding="utf-8"))


@dataclass(frozen=True)
class NeedPrediction:
    category: str
    probability: float | None = None
    evidence: str | None = None
    rule_id: str = "no_marker"
    evidence_type: str | None = None
    reason: str = "Недостаточно контекста для рекомендации"
    semantic_similarity: float | None = None
    confidence_label: str | None = None
    model_version: str = "needs-1.0"
    data_quality: str = "limited"

    @property
    def need_category(self):
        return self.category

    def as_dict(self) -> dict:
        result = asdict(self)
        result["need_category"] = result.pop("category")
        return result


def pattern_matches(pattern, text):
    return re.finditer(r"(?<!\w)(?:" + pattern + r")(?!\w)", text, flags=re.I)


def _negated(text, match, catalog):
    start = max((text.rfind(ch, 0, match.start()) for ch in ".;!?,\n"), default=-1) + 1
    ends = [i for ch in ".;!?,\n" if (i := text.find(ch, match.end())) >= 0]
    end = min(ends, default=len(text))
    before = text[max(start, match.start() - 65) : match.start()]
    after = text[match.end() : min(end, match.end() + 45)]
    return bool(
        re.search(catalog["negative_context"], before, re.I)
        or re.match(
            r"\s+(?:не\s+(?:требу\w*|предусмотр\w*|нуж\w*|планиру\w*)|отсутству\w*)", after, re.I
        )
    )


def explicit_and_blocked(text: str, catalog: dict) -> tuple[list[NeedPrediction], set[str]]:
    predictions, blocked = [], set()
    for category, spec in catalog["categories"].items():
        excluded = [m.span() for p in spec.get("exclude", []) for m in pattern_matches(p, text)]
        hits = [
            m
            for p in spec["explicit"]
            for m in pattern_matches(p, text)
            if not any(a < m.end() and m.start() < b for a, b in excluded)
        ]
        positive = [m for m in hits if not _negated(text, m, catalog)]
        if hits and not positive:
            blocked.add(category)
        if positive:
            hit = max(positive, key=lambda m: len(m.group()))
            start, end = max(0, hit.start() - 30), min(len(text), hit.end() + 45)
            predictions.append(
                NeedPrediction(
                    category=category,
                    evidence=text[start:end],
                    rule_id=f"rule:{category}",
                    evidence_type="explicit",
                    reason="Технология прямо упомянута в исходном тексте",
                    confidence_label="high",
                    model_version=catalog["model_version"],
                    data_quality="sufficient",
                )
            )
    return predictions, blocked


def matching_scenarios(text: str, catalog: dict) -> list[dict]:
    return [
        s
        for s in catalog.get("scenarios", [])
        if any(
            any(not _negated(text, m, catalog) for m in pattern_matches(p, text))
            for p in s["patterns"]
        )
    ]


def classify_need(
    title: str, description: str | None = None, *, catalog_path=None, max_recommendations: int = 3
) -> list[NeedPrediction]:
    if not 1 <= max_recommendations <= 3:
        raise ValueError("Допускается от 1 до 3 рекомендаций")
    text = "\n".join(t for t in (title, description) if t)
    catalog = load_catalog(catalog_path)
    predictions, blocked = explicit_and_blocked(text, catalog)
    seen = {p.category for p in predictions}
    for scenario in matching_scenarios(text, catalog):
        for category in scenario["needs"]:
            if category in seen or category in blocked:
                continue
            predictions.append(
                NeedPrediction(
                    category=category,
                    rule_id=f"inferred:{scenario['id']}",
                    evidence_type="inferred",
                    reason=catalog["categories"][category]["reason"],
                    confidence_label="low",
                    model_version=catalog["model_version"],
                )
            )
            seen.add(category)
    return predictions[:max_recommendations] or [
        NeedPrediction(
            UNKNOWN,
            rule_id="empty_input" if not text.strip() else "no_marker",
            model_version=catalog["model_version"],
            data_quality="insufficient",
        )
    ]


def contact_window(stage: str) -> str | None:
    return {
        "design": "6–12 мес. до старта",
        "modernization": "3–9 мес. до старта",
        "construction": "3–6 мес. до старта",
        "launch": "0–3 мес. до запуска",
        "completed": None,
    }.get(stage)
