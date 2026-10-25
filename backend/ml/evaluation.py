"""Оценка только по ручным меткам. Пустые поля никогда не становятся negative labels."""

import argparse
import json
from pathlib import Path

import numpy as np

from ml.needs import load_catalog


def annotation_template(projects: list[dict]) -> dict:
    return {
        "instructions": "Заполните explicit_categories и inferred_relevant; null = не размечено",
        "projects": [
            {
                "project_id": p["external_id"],
                "text": p["title"],
                "split": "test",
                "explicit_categories": None,
                "explicit_evidence": {},
                "inferred_relevant": None,
                "annotator": None,
            }
            for p in projects
        ],
    }


def evaluate(gold: dict, predictions: dict[str, list[dict]], *, split="test") -> dict:
    categories = set(load_catalog()["categories"])
    rows = [p for p in gold["projects"] if p.get("split") == split]
    if len({p["project_id"] for p in rows}) != len(rows):
        raise ValueError("Повторный project_id в разметке")
    labeled = [p for p in rows if p.get("explicit_categories") is not None]
    inferred = [p for p in rows if p.get("inferred_relevant") is not None]
    if not labeled and not inferred:
        return {"status": "not_evaluated", "reason": "Нет ручных меток", "split": split}
    if any(p["project_id"] not in predictions for p in labeled + inferred):
        raise ValueError("Для размеченного проекта нет предсказаний")
    for row in labeled:
        if (
            not isinstance(row["explicit_categories"], list)
            or set(row["explicit_categories"]) - categories
        ):
            raise ValueError("Некорректные explicit-метки")
        for category in row["explicit_categories"]:
            evidence = row.get("explicit_evidence", {}).get(category)
            if not evidence or evidence not in row["text"]:
                raise ValueError("Explicit-метка должна содержать точную цитату из текста")
    per_category, false_positives = {}, 0
    for category in sorted(categories):
        tp = fp = fn = 0
        for row in labeled:
            expected = category in row["explicit_categories"]
            predicted = any(
                p["need_category"] == category and p["evidence_type"] == "explicit"
                for p in predictions[row["project_id"]]
            )
            tp += expected and predicted
            fp += not expected and predicted
            fn += expected and not predicted
        precision = tp / (tp + fp) if tp + fp else 0
        recall = tp / (tp + fn) if tp + fn else 0
        per_category[category] = {
            "precision": precision,
            "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0,
            "tp": tp,
            "fp": fp,
            "fn": fn,
        }
        false_positives += fp
    p_at_3 = []
    for row in inferred:
        relevant = row["inferred_relevant"]
        if (
            not isinstance(relevant, dict)
            or set(relevant) - categories
            or any(not isinstance(v, bool) for v in relevant.values())
        ):
            raise ValueError("inferred_relevant должен содержать категории и экспертные true/false")
        top = [p for p in predictions[row["project_id"]] if p["evidence_type"] == "inferred"][:3]
        if any(p["need_category"] not in relevant for p in top):
            raise ValueError("Эксперт должен оценить каждую inferred-рекомендацию в top 3")
        # Фиксированный знаменатель 3: воздержание не повышает метрику искусственно.
        p_at_3.append(sum(relevant[p["need_category"]] for p in top) / 3)
    return {
        "status": "evaluated",
        "split": split,
        "explicit_projects": len(labeled),
        "inferred_projects": len(inferred),
        "per_category": per_category if labeled else None,
        "macro_precision": float(np.mean([v["precision"] for v in per_category.values()]))
        if labeled
        else None,
        "macro_recall": float(np.mean([v["recall"] for v in per_category.values()]))
        if labeled
        else None,
        "macro_f1": float(np.mean([v["f1"] for v in per_category.values()])) if labeled else None,
        "inferred_precision_at_3": float(np.mean(p_at_3)) if p_at_3 else None,
        "false_positive_explicit": false_positives if labeled else None,
        "without_recommendations": sum(
            not any(
                p["need_category"] != "insufficient_data"
                for p in predictions.get(row["project_id"], [])
            )
            for row in rows
        ),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, nargs="+", required=True)
    parser.add_argument("--split", default="test", choices=["dev", "test"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    gold = json.loads(args.gold.read_text(encoding="utf-8"))
    result = {}
    for path in args.predictions:
        data = json.loads(path.read_text(encoding="utf-8"))
        predictions = {p["external_id"]: p["recommendations"] for p in data["projects"]}
        result[str(path)] = evaluate(gold, predictions, split=args.split)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
