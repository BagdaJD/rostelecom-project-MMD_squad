"""Классификация потребностей инвестиционного проекта (AI-функция B, ТЗ 8.2).

MVP — правила с маркерами и доказательством: возвращаем конкретный фрагмент текста,
на основании которого сделан вывод. Это честнее, чем классификатор без доказательств.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

RULES: dict[str, tuple[str, ...]] = {
    "it_infrastructure": (
        "сервер",
        "цод",
        "центр обработки данных",
        "виртуализ",
        "облачн",
        "ixp",
        "стойко-мест",
        "ср",
        "схд",
        "имс",
    ),
    "connectivity": (
        "канал связи",
        "волокон",
        "оптич",
        "магистральн",
        "доступ в интернет",
        "л2с",
        "л3с",
        "телеком",
        "связь",
        "телефони",
        "vpn",
    ),
    "information_security": ("информационн", "безопасн", "сиэм", "dlp", "аик", "пн", "защит"),
    "video_surveillance": ("видеонаблюд", "камер", "видеорегистратор", "охранн"),
    "iot_asu_tp": ("асу тп", "асуэ", "диспетчеризац", "датчик", "телеметрии", "iot", "аис"),
}


PRIORITY = (
    "iot_asu_tp",
    "it_infrastructure",
    "video_surveillance",
    "information_security",
    "connectivity",
)

UNKNOWN = "insufficient_data"


@dataclass(frozen=True)
class NeedPrediction:
    category: str
    probability: float
    evidence: str | None
    rule_id: str


def _snippet(text: str, marker: str, window: int = 70) -> str:
    idx = text.lower().find(marker)
    if idx < 0:
        return text[:window]
    start = max(idx - window // 2, 0)
    return "…" + text[start : idx + len(marker) + window // 2].strip() + "…"


def classify_need(title: str, description: str | None = None) -> list[NeedPrediction]:
    text = f"{title or ''} {description or ''}".lower()
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return [NeedPrediction(UNKNOWN, 0.0, None, "empty_input")]

    hits: list[NeedPrediction] = []
    for category in PRIORITY:
        markers = [m for m in RULES[category] if m in text]
        if not markers:
            continue

        probability = round(min(0.45 + 0.15 * len(markers), 0.90), 2)
        longest = max(markers, key=len)
        hits.append(
            NeedPrediction(category, probability, _snippet(text, longest), f"rule:{category}")
        )

    return hits or [NeedPrediction(UNKNOWN, 0.2, None, "no_marker")]


def contact_window(stage: str) -> str | None:
    """Окно контакта по стадии — ТЗ 7."""
    return {
        "design": "6–12 мес. до старта",
        "modernization": "3–9 мес. до старта",
        "construction": "3–6 мес. до старта",
        "launch": "0–3 мес. до запуска",
        "completed": None,
    }.get(stage)
