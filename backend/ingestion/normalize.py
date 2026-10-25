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
from decimal import Decimal, InvalidOperation
from typing import Any

_COMPANY_SUFFIXES = ("ооо", "оао", "зао", "пао", "ао", "ип", "нко", "ау", "гбу", "мку", "ауно")
_WHITESPACE = re.compile(r"\s+")
_PUNCT = re.compile(r"[^0-9A-Za-zА-Яа-яЁё\s]+")
_LONG_FORMS = (
    "общество с ограниченной ответственностью",
    "публичное акционерное общество",
    "открытое акционерное общество",
    "закрытое акционерное общество",
    "акционерное общество",
    "индивидуальный предприниматель",
)


def normalize_name(name: str | None) -> str:
    """Нижний регистр, без пунктуации и организационно-правовых форм."""
    if not name:
        return ""
    value = unicodedata.normalize("NFKC", name).lower().replace("ё", "е")
    for form in _LONG_FORMS:
        value = value.replace(form, " ")
    value = _PUNCT.sub(" ", value)
    words = [w for w in _WHITESPACE.split(value) if w]
    while words and words[0] in _COMPANY_SUFFIXES:
        words.pop(0)
    return " ".join(words)


def is_valid_inn(value: str | None) -> bool:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{10}|[0-9]{12}", value):
        return False
    if len(set(value)) == 1:
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


def is_valid_ogrn(value: str | None) -> bool:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{13}|[0-9]{15}", value):
        return False
    if len(set(value)) == 1:
        return False
    divisor = 11 if len(value) == 13 else 13
    return int(value[:-1]) % divisor % 10 == int(value[-1])


def clean_text(value: Any, *, placeholder_136: bool = False) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in ("", "nan", "nat", "none", "null", "-", "—"):
        return None
    if placeholder_136 and text in ("136", "136.0"):
        return None
    return text


def identifier(value: Any) -> str | None:
    """Не дополняет идентификатор нулями: потерянные в источнике цифры неизвестны."""
    text = clean_text(value)
    if text and re.fullmatch(r"[0-9]+\.0", text):
        return text[:-2]
    return text


def number(value: Any) -> float | None:
    text = clean_text(value)
    if text is None:
        return None
    try:
        result = Decimal(text.replace("\u00a0", "").replace(" ", "").replace(",", "."))
        return float(result) if result.is_finite() else None
    except InvalidOperation:
        return None


def integer(value: Any) -> int | None:
    result = number(value)
    return int(result) if result is not None and result.is_integer() and result >= 0 else None


def iso_date(value: Any) -> str | None:
    text = clean_text(value)
    if text is None:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return None


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
    revenue: dict[int, float] = field(default_factory=dict)  # год → млн руб
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    source_url: str | None = None
    license_note: str | None = None
    municipality: str | None = None
    subject_type: str | None = None
    sme_category: str | None = None
    okved_description: str | None = None
    included_at: str | None = None
    excluded_at: str | None = None
    registered_at: str | None = None
    client_status: str = "unknown"
    dump_date: str | None = None

    def __post_init__(self):
        if isinstance(self.fetched_at, str):
            self.fetched_at = datetime.fromisoformat(self.fetched_at)

    def as_dict(self) -> dict:
        result = asdict(self)
        result["fetched_at"] = self.fetched_at.isoformat()
        return result

    def stable_payload(self) -> dict:
        result = self.as_dict()
        result.pop("fetched_at", None)
        return result


@dataclass
class MatchDecision:
    company_key: str
    method: str  # inn | ogrn | name_region | new
    confidence: float


def match_key(record: RawCompany) -> MatchDecision:
    """Ключ объединения: ИНН надёжнее имени, имя без региона не объединяем."""
    if record.inn and is_valid_inn(record.inn):
        return MatchDecision(f"inn:{record.inn}", "inn", 1.0)
    if is_valid_ogrn(record.ogrn):
        return MatchDecision(f"ogrn:{record.ogrn}", "ogrn", 1.0)
    normalized = normalize_name(record.name)
    if normalized and record.region_code:
        # Уверенность ниже единицы намеренно: объединение по имени всегда требует проверки.
        return MatchDecision(f"name:{normalized}|{record.region_code}", "name_region", 0.75)
    return MatchDecision(f"new:{payload_hash(record.stable_payload())[:16]}", "new", 0.0)


def clean_revenue(values: dict[int, float] | None) -> dict[int, float]:
    """Отрицательная и нулевая «выручка» из источников — почти всегда мусор: отбрасываем."""
    if not values:
        return {}
    return {int(y): float(v) for y, v in values.items() if v is not None and float(v) > 0}
