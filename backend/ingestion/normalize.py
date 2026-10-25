"""Нормализация и дедупликация: вход для любого адаптера источника (ТЗ 6.8).

Правила:
• пропуск остаётся пропуском (None), а не нулём;
• компания матчится сначала по ИНН/ОГРН, затем по нормализованному имени + региону
  с явной уверенностью;
• каждая загрузка оставляет SourceRecord с hash полезной нагрузки.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

_COMPANY_SUFFIXES = ("ооо", "оао", "зао", "пао", "ао", "ип", "нко", "ау", "гбу", "мку", "ауно")
_WHITESPACE = re.compile(r"\s+")
_PUNCT = (
    re.compile(r"[^\p{L}\p{N}\s]+", re.UNICODE) if False else re.compile(r"[^0-9A-Za-zА-Яа-яЁё\s]+")
)


def normalize_name(name: str | None) -> str:
    """Нижний регистр, без пунктуации и организационно-правовых форм."""
    if not name:
        return ""
    value = unicodedata.normalize("NFKC", name).lower().replace("ё", "е")
    value = re.sub(
        r"^(?:публичное\s+|непубличное\s+|открытое\s+|закрытое\s+)?акционерное общество\s*"
        r"|^общество с ограниченной ответственностью\s*|^индивидуальный предприниматель\s*",
        "",
        value,
    )
    value = _PUNCT.sub(" ", value)
    words = [w for w in _WHITESPACE.split(value) if w]
    while words and words[0] in _COMPANY_SUFFIXES:
        words.pop(0)
    words = [w for w in words if w not in _COMPANY_SUFFIXES]
    return " ".join(words)


def is_valid_inn(value: str | None) -> bool:
    if not value or not value.isdigit():
        return False
    if len(value) not in (10, 12):
        return False
    weights10 = [2, 4, 10, 3, 5, 9, 4, 6, 8]
    weights12 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
    digits = [int(c) for c in value]
    if len(digits) == 10:
        control = sum(w * d for w, d in zip(weights10, digits[:9], strict=True)) % 11 % 10
        return control == digits[9]
    control11 = sum(w * d for w, d in zip(weights12, digits[:10], strict=True)) % 11 % 10
    control12 = sum(w * d for w, d in zip([3, *weights12], digits[:11], strict=True)) % 11 % 10
    return control11 == digits[10] and control12 == digits[11]


def payload_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()


@dataclass
class RawCompany:
    source: str
    external_id: str | None
    name: str
    inn: str | None = None
    ogrn: str | None = None
    industry_code: str | None = None
    region_code: str | None = None
    employee_count: int | None = None
    revenue: dict[int, float] = field(default_factory=dict)
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    source_url: str | None = None
    license_note: str | None = None
    municipality: str | None = None
    city: str | None = None
    settlement: str | None = None
    is_synthetic: bool = False
    attributes: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.fetched_at, str):
            self.fetched_at = datetime.fromisoformat(self.fetched_at)
        if self.fetched_at.tzinfo is None:
            self.fetched_at = self.fetched_at.replace(tzinfo=UTC)

    def as_dict(self) -> dict:
        payload = asdict(self)
        payload["fetched_at"] = self.fetched_at.isoformat()
        return payload


@dataclass
class MatchDecision:
    company_key: str
    method: str
    confidence: float


def match_key(record: RawCompany) -> MatchDecision:
    """Ключ объединения: ИНН надёжнее имени, имя без региона не объединяем."""
    if record.inn and is_valid_inn(record.inn):
        return MatchDecision(f"inn:{record.inn}", "inn", 1.0)
    if record.ogrn and len(record.ogrn) in (13, 15):
        return MatchDecision(f"ogrn:{record.ogrn}", "ogrn", 1.0)
    normalized = normalize_name(record.name)
    if normalized and record.region_code:
        return MatchDecision(f"name:{normalized}|{record.region_code}", "name_region", 0.75)
    content = {k: v for k, v in record.as_dict().items() if k != "fetched_at"}
    return MatchDecision(f"new:{payload_hash(content)[:16]}", "new", 0.0)


def clean_revenue(values: dict[int, float] | None) -> dict[int, float]:
    """Известный ноль сохраняется; пропуски и отрицательная выручка исключаются."""
    if not values:
        return {}
    return {int(y): float(v) for y, v in values.items() if v is not None and float(v) >= 0}
