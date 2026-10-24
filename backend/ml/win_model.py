"""Шанс выиграть сделку: многофакторная логистическая регрессия (scikit-learn).

Признаки: наценка (цена ÷ себестоимость), тип объекта, площадь, уровень проекта, зона
региона, схема оплаты, госзаказчик. Проверка честная — по времени: обучение на ранних
сделках, проверка на последних 25 %; рядом всегда базовая модель «только наценка», чтобы
было видно, даёт ли многофакторность что-то сверх неё.

Модель отдаёт:
* ``p(index)`` — шанс выиграть при заданной наценке для конкретного проекта (остальные
  признаки зафиксированы) — для кривой «маржа ↔ шанс» и оптимума;
* ``factors(...)`` — вклад каждого фактора в процентных пунктах: насколько шанс выше или
  ниже, чем у «типичного» проекта; так объясняется рекомендация.

Пока история сделок синтетическая, метрики показывают, что модель восстанавливает
заложенные в генератор закономерности, а не реальный рынок (см. docs/model-limits.md).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import date

NUMERIC = ("price_index", "log_area", "level")
CATEGORICAL = ("object_type", "zone", "payment_scheme", "budget_customer")
LEVELS = {"basic": 0, "advanced": 1, "expert": 2}
ZONE_LABELS = {"RU-ROS": "Ростовская обл.", "ZONE-CEN": "Центр", "ZONE-NW": "Северо-Запад",
               "ZONE-S": "Юг", "ZONE-URV": "Урал и Поволжье", "ZONE-FES": "Сибирь и Дальний Восток"}
FACTOR_LABELS = {
    "price_index": "Наценка",
    "log_area": "Площадь объекта",
    "level": "Уровень проекта",
    "object_type": "Тип объекта",
    "zone": "Регион",
    "payment_scheme": "Схема оплаты",
    "budget_customer": "Госзаказчик (44-ФЗ)",
}


@dataclass(frozen=True)
class DealRow:
    """Одна сделка для обучения или запрос для прогноза (outcome=None)."""

    price_index: float
    area_m2: float | None
    project_level: str | None
    object_type: str | None
    zone: str | None
    payment_scheme: str | None
    budget_customer: bool
    outcome: str | None = None
    closed_at: date | None = None
    basis: str = "synthetic"  # contract | estimate | synthetic — природа цены сделки

    def features(self, price_index: float | None = None) -> dict:
        return {
            "price_index": self.price_index if price_index is None else price_index,
            "log_area": math.log(self.area_m2) if self.area_m2 and self.area_m2 > 0 else 8.3,
            "level": LEVELS.get(self.project_level or "basic", 0),
            "object_type": self.object_type or "unknown",
            "zone": self.zone or "unknown",
            "payment_scheme": self.payment_scheme or "capex",
            "budget_customer": "yes" if self.budget_customer else "no",
        }


@dataclass
class Quality:
    model: str
    n_train: int
    n_test: int
    auc: float | None
    auc_baseline: float | None
    brier: float | None
    basis: str  # synthetic | contract | mixed

    def as_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class TrainedWinModel:
    pipeline: object
    quality: Quality
    reference: dict  # «типичный» проект: медианы и самые частые категории
    columns: list[str] = field(default_factory=list)

    def predict(self, rows: list[dict]) -> list[float]:
        import pandas as pd

        frame = pd.DataFrame(rows, columns=self.columns)
        return [float(p) for p in self.pipeline.predict_proba(frame)[:, 1]]

    def bind(self, query: DealRow) -> BoundWinModel:
        """Незаполненные признаки проекта считаем типичными, а не отдельной категорией."""
        ref = self.reference
        query = replace(
            query,
            object_type=query.object_type or ref["object_type"],
            zone=query.zone or ref["zone"],
            payment_scheme=query.payment_scheme or ref["payment_scheme"],
            area_m2=query.area_m2 or math.exp(ref["log_area"]),
        )
        return BoundWinModel(self, query)


@dataclass
class BoundWinModel:
    """Модель, привязанная к проекту: p(наценка) при остальных признаках этого проекта.

    Интерфейс совпадает с ml.deal_pricing.WinModel (метод p и поле basis).
    """

    model: TrainedWinModel
    query: DealRow

    @property
    def basis(self) -> str:
        return self.model.quality.basis

    @property
    def n(self) -> int:
        return self.model.quality.n_train + self.model.quality.n_test

    def p(self, index: float) -> float:
        return self.model.predict([self.query.features(index)])[0]

    def curve(self, indices: list[float]) -> list[float]:
        return self.model.predict([self.query.features(i) for i in indices])

    def factors(self, index: float) -> list[dict]:
        """Вклад факторов, п.п.: шанс проекта минус шанс, если заменить фактор на типичный."""
        base = self.query.features(index)
        p_base = self.model.predict([base])[0]
        out = []
        for name in (*NUMERIC, *CATEGORICAL):
            ref_value = self.model.reference[name]
            if base[name] == ref_value:
                continue
            swapped = {**base, name: ref_value}
            delta = p_base - self.model.predict([swapped])[0]
            out.append({
                "factor": name,
                "label": FACTOR_LABELS[name],
                "value": _describe(name, base[name]),
                "typical": _describe(name, ref_value),
                "delta_pp": round(delta * 100, 1),
            })
        return sorted(out, key=lambda f: -abs(f["delta_pp"]))


def _describe(name: str, value) -> str:
    if name == "price_index":
        return f"×{value:.2f}".replace(".", ",")
    if name == "log_area":
        return f"{round(math.exp(value), -1):,.0f} м²".replace(",", " ")
    if name == "level":
        return {0: "базовый", 1: "продвинутый", 2: "экспертный"}.get(int(round(value)), str(value))
    if name == "budget_customer":
        return "да" if value == "yes" else "нет"
    if name == "payment_scheme":
        return {"capex": "сразу", "installment": "рассрочка", "opex": "сервис"}.get(value, value)
    if name == "object_type":
        from ml.deal_cost import OBJECT_TYPES

        return OBJECT_TYPES.get(value, {}).get("label", value).lower()
    if name == "zone":
        return ZONE_LABELS.get(value, value)
    return str(value)


def train(rows: list[DealRow], min_rows: int = 60, test_share: float = 0.25,
          random_state: int = 0) -> TrainedWinModel | None:
    """Обучение с проверкой по времени. None — если данных мало или нет sklearn."""
    labelled = [r for r in rows if r.outcome in ("won", "lost") and r.price_index > 0]
    if len(labelled) < min_rows or len({r.outcome for r in labelled}) < 2:
        return None
    try:
        import pandas as pd
        from sklearn.compose import ColumnTransformer
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import brier_score_loss, roc_auc_score
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import OneHotEncoder, StandardScaler
    except ImportError:  # sklearn не установлен — остаётся базовая модель
        return None

    labelled.sort(key=lambda r: r.closed_at or date.min)
    split = int(len(labelled) * (1 - test_share))
    train_rows, test_rows = labelled[:split], labelled[split:]
    columns = [*NUMERIC, *CATEGORICAL]

    def frame(rs: list[DealRow]):
        return pd.DataFrame([r.features() for r in rs], columns=columns)

    def target(rs: list[DealRow]) -> list[int]:
        return [1 if r.outcome == "won" else 0 for r in rs]

    def make(cols_num: tuple[str, ...], cols_cat: tuple[str, ...]):
        steps = [("num", StandardScaler(), list(cols_num))]
        if cols_cat:
            steps.append(("cat", OneHotEncoder(handle_unknown="ignore"), list(cols_cat)))
        return Pipeline([
            ("prep", ColumnTransformer(steps)),
            ("clf", LogisticRegression(C=1.0, max_iter=1000, random_state=random_state)),
        ])

    full = make(NUMERIC, CATEGORICAL)
    baseline = make(("price_index",), ())
    auc = auc_base = brier = None
    y_test = target(test_rows)
    if len(set(y_test)) == 2 and len(set(target(train_rows))) == 2:
        full.fit(frame(train_rows), target(train_rows))
        baseline.fit(frame(train_rows), target(train_rows))
        p_full = full.predict_proba(frame(test_rows))[:, 1]
        p_base = baseline.predict_proba(frame(test_rows))[:, 1]
        auc = round(float(roc_auc_score(y_test, p_full)), 3)
        auc_base = round(float(roc_auc_score(y_test, p_base)), 3)
        brier = round(float(brier_score_loss(y_test, p_full)), 3)

    # Для работы — обучаем на всей истории: метрики выше уже честно посчитаны на отложенной.
    full.fit(frame(labelled), target(labelled))

    feats = frame(labelled)
    reference = {name: float(feats[name].median()) for name in NUMERIC}
    reference["level"] = float(round(reference["level"]))
    for name in CATEGORICAL:
        reference[name] = str(feats[name].mode().iloc[0])

    bases = {r.basis for r in labelled}
    quality = Quality(
        model="LogisticRegression (scikit-learn)",
        n_train=len(train_rows), n_test=len(test_rows),
        auc=auc, auc_baseline=auc_base, brier=brier,
        basis=bases.pop() if len(bases) == 1 else "mixed",
    )
    return TrainedWinModel(pipeline=full, quality=quality, reference=reference,
                           columns=columns)
