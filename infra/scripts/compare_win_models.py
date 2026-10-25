#!/usr/bin/env python3
"""Сравнение моделей шанса выиграть: логистическая регрессия vs CatBoost.

Данные синтетические, поэтому известна ИСТИННАЯ вероятность выигрыша каждой сделки —
можно мерить не только AUC, но и насколько модель ошибается в вероятности и сколько
ожидаемой прибыли теряется, если ставить цену по её оптимуму.

Сценарии: A — рынок как в демо-данных (генератор import_case_xlsx.py); B — нелинейный
рынок (на госторгах шанс падает с ценой резче, у крупных объектов свой порог) — проверка,
не выигрывает ли CatBoost, когда закономерность не укладывается в логистическую формулу.

Запуск из корня репозитория (нужен CatBoost: pip install -e "backend[ml]")::

    python3 infra/scripts/compare_win_models.py

Результаты и выводы — docs/calculator-win-model.md.
"""
import math
import random
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import openpyxl
import pandas as pd
from catboost import CatBoostClassifier
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "infra/scripts"))
import import_case_xlsx as gen  # noqa: E402
from ml.win_model import CATEGORICAL, NUMERIC, DealRow  # noqa: E402

wb = openpyxl.load_workbook(ROOT / "data/case/case_data_2026.xlsx", data_only=True)
_, coefs = gen.read_zones(wb)
POS = gen.read_positions(wb)
PROJ, _ = gen.read_projects(wb)
ZONES = {c["region_code"]: c["coefficient"] for c in coefs}
COLS = [*NUMERIC, *CATEGORICAL]
GRID = np.round(np.arange(1.10, 1.751, 0.01), 2)


def market(d):
    return (gen.TYPE_SHIFT[d["object_type"]] + gen.LEVEL_SHIFT[d["project_level"]]
            + gen.PAYMENT_SHIFT[d["payment_scheme"]]
            + (gen.BUDGET_SHIFT if d["financing_scheme"] == "budget" else 0.0))


def truth_a(d, idx):  # как в генераторе: логистика по наценке + аддитивные сдвиги
    return 1 / (1 + math.exp(gen.STEEPNESS * (idx - gen.I50 - market(d))))


def truth_b(d, idx):  # нелинейный рынок: госторги жёстко по цене, крупные объекты иначе
    k = 32.0 if d["financing_scheme"] == "budget" else 11.0
    big = 0.04 if d["area_m2"] > 8000 else 0.0
    return 1 / (1 + math.exp(k * (idx - gen.I50 - market(d) - big)))


def dataset(n, seed, truth):
    deals = gen.generate_deals(n, seed, PROJ, POS, ZONES)
    rnd = random.Random(seed + 10_000)
    for d in deals:
        d["idx"] = d["contract_value"] / d["cost_value"]
        d["p_true"] = truth(d, d["idx"])
        d["outcome"] = "won" if rnd.random() < d["p_true"] else "lost"
    deals.sort(key=lambda d: d["closed_at"])
    return deals


def row(d, idx=None):
    r = DealRow(d["idx"], d["area_m2"], d["project_level"], d["object_type"],
                d["region_code"][:6] if d["region_code"].startswith("RU-ROS") else d["region_code"],
                d["payment_scheme"], d["financing_scheme"] == "budget")
    return r.features(idx)


def lr(cols_num, cols_cat):
    steps = [("num", StandardScaler(), list(cols_num))]
    if cols_cat:
        steps.append(("cat", OneHotEncoder(handle_unknown="ignore"), list(cols_cat)))
    return Pipeline([("prep", ColumnTransformer(steps)),
                     ("clf", LogisticRegression(C=1.0, max_iter=1000))])


class CB:
    def __init__(self, monotone):
        kw = dict(iterations=400, depth=4, learning_rate=0.05, verbose=0, random_seed=0,
                  cat_features=list(CATEGORICAL), allow_writing_files=False)
        if monotone:
            kw["monotone_constraints"] = {"price_index": -1}
        self.m = CatBoostClassifier(**kw)

    def fit(self, X, y):
        self.m.fit(X, y)
        return self

    def predict_proba(self, X):
        return self.m.predict_proba(X)


MODELS = {
    "Только наценка (LR)": lambda: lr(("price_index",), ()),
    "Логистическая регрессия, 7 признаков": lambda: lr(NUMERIC, CATEGORICAL),
    "CatBoost": lambda: CB(False),
    "CatBoost + монотонность по цене": lambda: CB(True),
}


def evaluate(deals, truth):
    split = int(len(deals) * 0.75)
    tr, te = deals[:split], deals[split:]
    Xtr = pd.DataFrame([row(d) for d in tr], columns=COLS)
    ytr = [d["outcome"] == "won" for d in tr]
    Xte = pd.DataFrame([row(d) for d in te], columns=COLS)
    yte = [d["outcome"] == "won" for d in te]
    # кривые «наценка → шанс» для каждой тестовой сделки
    Xcurve = pd.DataFrame([row(d, float(i)) for d in te for i in GRID], columns=COLS)
    true_curve = np.array([[truth(d, float(i)) for i in GRID] for d in te])
    true_profit = (GRID - 1) * true_curve
    best = true_profit.max(axis=1)
    out = {}
    for name, make in MODELS.items():
        t0 = time.time()
        m = make().fit(Xtr, ytr)
        p = m.predict_proba(Xte)[:, 1]
        curve = m.predict_proba(Xcurve)[:, 1].reshape(len(te), len(GRID))
        chosen = (GRID - 1)[None, :] * curve
        pick = chosen.argmax(axis=1)
        got = true_profit[np.arange(len(te)), pick]
        out[name] = {
            "auc": roc_auc_score(yte, p),
            "brier": brier_score_loss(yte, p),
            "mae_p": float(np.mean(np.abs(p - np.array([d["p_true"] for d in te])))),
            "regret": float(np.mean((best - got) / best)),
            "nonmono": float(np.mean((np.diff(curve, axis=1) > 0.01).any(axis=1))),
            "tail": float(curve[:, -1].mean()),
            "tail_true": float(true_curve[:, -1].mean()),
            "sec": time.time() - t0,
        }
    return out


def run(label, n, seeds, truth):
    agg = {}
    for s in seeds:
        for name, r in evaluate(dataset(n, s, truth), truth).items():
            for k, v in r.items():
                agg.setdefault(name, {}).setdefault(k, []).append(v)
    print(f"\n### {label}: {n} сделок, {len(seeds)} генераций "
          "(обучение 75 % ранних, проверка 25 % поздних)")
    print("| Модель | ROC-AUC | Brier ↓ | Ошибка вероятности ↓ | Потеря прибыли от оптимума ↓ "
          "| Шанс при наценке ×1,75 (истина) | Кривых, где цена↑ → шанс↑ |")
    print("|---|---|---|---|---|---|---|")
    for name, r in agg.items():
        m = {k: np.mean(v) for k, v in r.items()}
        sd = np.std(r["auc"])
        print(f"| {name} | {m['auc']:.3f} ± {sd:.3f} | {m['brier']:.3f} "
              f"| {m['mae_p'] * 100:.1f} п.п. | {m['regret'] * 100:.1f} % "
              f"| {m['tail'] * 100:.0f} % ({m['tail_true'] * 100:.0f} %) "
              f"| {m['nonmono'] * 100:.0f} % |")


if __name__ == "__main__":
    run("A. Рынок как в демо-данных", 400, range(20), truth_a)
    run("A. Рынок как в демо-данных", 3000, range(5), truth_a)
    run("B. Нелинейный рынок (госторги жёстче по цене, крупные объекты)", 400, range(20), truth_b)
    run("B. Нелинейный рынок (госторги жёстче по цене, крупные объекты)", 3000, range(5), truth_b)
