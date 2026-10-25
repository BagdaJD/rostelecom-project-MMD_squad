"""Воспроизводимый пакетный pipeline и отчёт только с агрегатами."""

import hashlib
import json
from collections import Counter
from dataclasses import asdict
from datetime import date
from pathlib import Path
from time import perf_counter

import numpy as np

from ingestion.features import company_features, project_features
from ingestion.matching import unique_companies
from ingestion.normalize import RawCompany
from ingestion.sources.excel_source import read_excel
from ingestion.sources.fns_source import LocalFnsSource
from ml.geo_scoring import find_white_spaces, score_territories
from ml.needs import UNKNOWN, NeedPrediction
from ml.recommender import HybridRecommender
from ml.scoring import load_scoring_config, score_company


def analyze(
    companies: list[RawCompany],
    projects: list[dict],
    *,
    as_of: date,
    recommender=None,
    quality=None,
    reuse_recommendations=False,
) -> dict:
    unique, matching = unique_companies(companies)
    projects = [project_features(p) for p in projects]
    recommender = recommender or HybridRecommender()
    start = perf_counter()
    if reuse_recommendations:
        if any("recommendations" not in p for p in projects):
            raise ValueError("Для score сначала выполните NLP")
        predictions = [
            [
                NeedPrediction(
                    category=r["need_category"],
                    **{k: v for k, v in r.items() if k != "need_category"},
                )
                for r in p["recommendations"]
            ]
            for p in projects
        ]
        recommender.semantic_status = "reused_saved_results"
    else:
        predictions = recommender.predict_batch(projects)
    nlp_seconds = perf_counter() - start
    for project, needs in zip(projects, predictions, strict=True):
        project["recommendations"] = [n.as_dict() for n in needs]
    features, project_matching = company_features(unique, projects)
    scoring_config = load_scoring_config()
    scores = [score_company(c, as_of=as_of, config=scoring_config) for c in features]
    for c, score in zip(features, scores, strict=True):
        c["scoring"] = score
        c["confirmed_projects"] = [p["external_id"] for p in c["confirmed_projects"]]
    territories = score_territories(features, projects, config=scoring_config)
    needs = [n for ps in predictions for n in ps if n.category != UNKNOWN]
    score_values = [s["score"] for s in scores if s["score"] is not None]
    score_counts = Counter(score_values)
    warnings = []
    if score_values and max(score_counts.values()) / len(score_values) >= 0.8:
        warnings.append(
            "Не менее 80% компаний получили одинаковый score; данные мало различают лиды"
        )
    quality = {
        **(quality or {}),
        "entity_matching": matching,
        "project_matching": project_matching,
        "companies": len(unique),
        "projects": len(projects),
        "feature_coverage": {
            k: round(sum(c.get(k) is not None for c in features) / len(features), 6)
            if features
            else 0
            for k in ("industry", "employee_count", "sme_category", "municipality", "included_at")
        },
        "feature_missing_counts": {
            k: sum(c.get(k) is None for c in features)
            for k in ("industry", "employee_count", "sme_category", "municipality", "included_at")
        },
        "nlp": {
            "seconds": nlp_seconds,
            "semantic_status": recommender.semantic_status,
            "categories": dict(Counter(n.category for n in needs)),
            "evidence_types": dict(Counter(n.evidence_type for n in needs)),
            "without_recommendations": sum(ps[0].category == UNKNOWN for ps in predictions),
        },
        "company_scores": {
            "histogram": dict(Counter(str(int(v // 10) * 10) for v in score_values)),
            "min": min(score_values, default=None),
            "max": max(score_values, default=None),
            "unique_scores": len(score_counts),
            "data_quality": dict(Counter(s["data_quality"] for s in scores)),
            "priorities": dict(Counter(s["priority_category"] or "unknown" for s in scores)),
            "insufficient_share": sum(s["score"] is None for s in scores) / len(scores)
            if scores
            else None,
        },
        "territory_scores": {
            "count": len(territories),
            "histogram": dict(
                Counter(str(int(c["potential_score"] // 10) * 10) for c in territories)
            ),
            "insufficient_presence": sum(c["presence_score"] is None for c in territories),
        },
        "evaluation": {"status": "not_evaluated", "reason": "Нет экспертной разметки"},
        "warnings": [*(quality or {}).get("warnings", []), *warnings],
    }
    # Отдельный замер single-project latency; пакетная загрузка модели уже завершена.
    latency = []
    for project in [] if reuse_recommendations else projects:
        start = perf_counter()
        recommender.predict_batch([project])
        latency.append((perf_counter() - start) * 1000)
    quality["nlp"]["warm_latency_ms"] = {
        "mean": float(np.mean(latency)) if latency else None,
        "p95": float(np.percentile(latency, 95)) if latency else None,
        "memory": "not_measured: tracemalloc не учитывает нативную память torch",
    }
    return {
        "format_version": "mmd-pipeline-1",
        "as_of": as_of.isoformat(),
        "configuration": {
            "catalog_version": recommender.catalog["model_version"],
            "embedding": {
                **asdict(recommender.ranker.config),
                "resolved_revision": recommender.ranker.resolved_revision,
            }
            if recommender.ranker
            else None,
            "scoring": load_scoring_config(),
        },
        "source_records": [c.stable_payload() for c in companies],
        "companies": features,
        "projects": projects,
        "territories": territories,
        "white_spaces": find_white_spaces(territories),
        "quality": quality,
    }


def run_pipeline(
    excel: str | Path, *, as_of: date, fns: str | Path | None = None, recommender=None
) -> dict:
    before = hashlib.sha256(Path(excel).read_bytes()).hexdigest()
    data = read_excel(excel)
    records = data.companies
    if fns:
        source = LocalFnsSource(fns)
        records.extend(source.iter_companies())
        data.quality["fns"] = {"counts": dict(source.counts), "errors": source.errors}
    result = analyze(
        records, data.projects, as_of=as_of, recommender=recommender, quality=data.quality
    )
    if before != hashlib.sha256(Path(excel).read_bytes()).hexdigest():
        raise RuntimeError("Исходный Excel изменился во время обработки")
    result["quality"]["input_sha256"] = before
    result["quality"]["original_unchanged"] = True
    return result


def write_result(result: dict, output: str | Path):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with (output / "normalized.json").open("w", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    (output / "quality.json").write_text(
        json.dumps(result["quality"], ensure_ascii=False, indent=2), encoding="utf-8"
    )
