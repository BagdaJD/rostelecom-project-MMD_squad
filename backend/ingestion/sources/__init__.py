"""Адаптеры источников.

Внешние API (ФНС, ЕИС, реестры инвестиций) подключаются только после проверки
условий использования, наличия официального API и допустимой частоты запросов —
см. docs/data-sources.md. Поэтому реальные адаптеры здесь выключены по умолчанию,
а для демонстрации работает `DemoSource`, читающий локальный синтетический набор.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path

SOURCES: dict[str, type[BaseSource]] = {}


def register(name: str):
    def decorator(cls):
        SOURCES[name] = cls
        return cls

    return decorator


class BaseSource(ABC):
    name: str = "base"
    #: Требуется ли явное включение (внешние источники — да).
    requires_consent = True

    @abstractmethod
    def fetch(self) -> dict:
        """Возвращает bundle в формате data/seed/demo_bundle.json."""

    def license_note(self) -> str:
        return "условия использования не проверены"


@register("demo")
class DemoSource(BaseSource):
    """Локальный синтетический набор: легален, воспроизводим, помечен как демо."""

    name = "demo"
    requires_consent = False

    def __init__(self, path: Path | str | None = None) -> None:
        default = Path(__file__).resolve().parents[3] / "data" / "seed" / "demo_bundle.json"
        self.path = Path(path or default)

    def fetch(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def license_note(self) -> str:
        return "синтетические данные, созданы для демонстрации"


@register("fns")
class FnsSource(BaseSource):
    """Совместимый адаптер локального файла; сетевых обращений нет."""

    name = "fns"

    def __init__(self, path: Path | str, region_code: str = "61", dump_date=None):
        from ingestion.sources.fns_source import LocalFnsSource

        self.local = LocalFnsSource(path, region_code, dump_date)

    def fetch(self) -> dict:
        records = list(self.local.iter_companies())
        return {
            "companies": [c.as_dict() for c in records],
            "quality": {"counts": dict(self.local.counts), "errors": self.local.errors},
        }


@register("eis")
class EisSource(BaseSource):
    """Заглушка ЕИС закупок (zakupki.gov.ru)."""

    name = "eis"

    def fetch(self) -> dict:
        raise NotImplementedError(
            "Доступ к ЕИС согласуется отдельно: открытый каталог, частота запросов, лицензии"
        )


def get_source(name: str, **kwargs) -> BaseSource | None:
    cls = SOURCES.get(name)
    return cls(**kwargs) if cls else None


def enabled_sources(consent_granted: bool = False) -> list[str]:
    """Источники, которые можно запускать прямо сейчас."""
    return [n for n, cls in SOURCES.items() if not cls.requires_consent or consent_granted]
