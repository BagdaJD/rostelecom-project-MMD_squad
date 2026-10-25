"""Диагностика NLP и рейтингов без создания экспертных истинных меток."""

import argparse
import json
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date
from pathlib import Path
from time import perf_counter

import numpy as np

from ml.embeddings import EmbeddingConfig, SemanticRanker
from ml.needs import UNKNOWN, explicit_and_blocked, load_catalog, matching_scenarios
from ml.recommender import HybridRecommender
from ml.runtime import RuntimeMeasurement
from ml.scoring import load_scoring_config, score_company


def distribution(values):
    values = np.array([v for v in values if v is not None], dtype=float)
    if not len(values):
        return {"count": 0}
    return {
        "count": len(values),
        "min": float(values.min()),
        "max": float(values.max()),
        "mean": float(values.mean()),
        **{f"p{q}": float(np.percentile(values, q)) for q in (5, 25, 50, 75, 95)},
        "histogram_10_bins": np.histogram(values, bins=10)[0].tolist(),
        "histogram_edges": np.histogram(values, bins=10)[1].tolist(),
    }


def _rank(values):
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = np.empty(len(values))
    i = 0
    while i < len(order):
        end = i + 1
        while end < len(order) and values[order[end]] == values[order[i]]:
            end += 1
        ranks[order[i:end]] = (i + end - 1) / 2
        i = end
    return ranks


def scoring_diagnostics(data):
    companies = data["companies"]
    projects = {p["external_id"]: p for p in data["projects"]}
    as_of = date.fromisoformat(data["as_of"])
    features = [
        {**c, "confirmed_projects": [projects[pid] for pid in c["confirmed_projects"]]}
        for c in companies
    ]
    config = load_scoring_config()
    scores = [score_company(c, as_of=as_of, config=config) for c in features]
    observed = [s["score"] for s in scores if s["score"] is not None]
    by_industry, by_category = defaultdict(list), defaultdict(list)
    for company, score in zip(companies, scores, strict=True):
        by_industry[company.get("industry") or "unknown"].append(score["score"])
        by_category[company.get("sme_category") or "unknown"].append(score["score"])
    ordered = sorted(
        (i for i, s in enumerate(scores) if s["score"] is not None),
        key=lambda i: (-scores[i]["score"], i),
    )

    def examples(indices):
        return [
            {
                "rank": n + 1,
                "industry": companies[i].get("industry"),
                "sme_category": companies[i].get("sme_category"),
                "size_basis": scores[i]["size_basis"],
                "score": scores[i]["score"],
                "feature_coverage": scores[i]["feature_coverage"],
                "data_quality": scores[i]["data_quality"],
                "factors": scores[i]["factors"],
                "explanation": scores[i]["explanation"],
                "observed_weighted_lower_bound": round(
                    scores[i]["score"] * scores[i]["feature_coverage"], 2
                ),
                "unknown_factor_upper_bound": round(
                    scores[i]["score"] * scores[i]["feature_coverage"]
                    + 100 * (1 - scores[i]["feature_coverage"]),
                    2,
                ),
            }
            for n, i in enumerate(indices)
        ]

    sensitivity = []
    if observed and len(observed) == len(scores):
        ranks = _rank(observed)
        original_top = set(ordered[:10])
        for factor in config["company_weights"]:
            for multiplier in (0.8, 1.2):
                changed = deepcopy(config)
                changed["company_weights"][factor] *= multiplier
                total = sum(changed["company_weights"].values())
                changed["company_weights"] = {
                    k: w / total for k, w in changed["company_weights"].items()
                }
                result = [score_company(c, as_of=as_of, config=changed)["score"] for c in features]
                if any(v is None for v in result):
                    sensitivity.append(
                        {
                            "factor": factor,
                            "multiplier": multiplier,
                            "status": "changed_abstention_coverage",
                        }
                    )
                    continue
                top = set(sorted(range(len(result)), key=lambda i: (-result[i], i))[:10])
                sensitivity.append(
                    {
                        "factor": factor,
                        "multiplier": multiplier,
                        "max_absolute_score_delta": max(
                            abs(a - b) for a, b in zip(observed, result, strict=True)
                        ),
                        "mean_absolute_score_delta": float(
                            np.mean(np.abs(np.array(result) - observed))
                        ),
                        "spearman_with_average_ties": float(np.corrcoef(ranks, _rank(result))[0, 1])
                        if np.std(ranks) and np.std(_rank(result))
                        else None,
                        "top10_jaccard": len(original_top & top) / len(original_top | top),
                    }
                )
    return {
        "companies": len(companies),
        "scores": distribution(observed),
        "unique_scores": len(set(observed)),
        "largest_tie_group": max(Counter(observed).values(), default=0),
        "by_industry": {k: distribution(v) for k, v in by_industry.items()},
        "by_sme_category": {k: distribution(v) for k, v in by_category.items()},
        "quality": dict(Counter(s["data_quality"] for s in scores)),
        "priorities": dict(Counter(s["priority_category"] or "unknown" for s in scores)),
        "size_basis": dict(Counter(s["size_basis"] for s in scores)),
        "coverage": distribution([s["feature_coverage"] for s in scores]),
        "factors": {
            k: {
                "available": sum(
                    f["available"] for s in scores for f in s["factors"] if f["code"] == k
                ),
                "contribution": distribution(
                    [f["contribution"] for s in scores for f in s["factors"] if f["code"] == k]
                ),
            }
            for k in config["company_weights"]
        },
        "top10": examples(ordered[:10]),
        "bottom10": examples(list(reversed(ordered[-10:]))),
        "sensitivity_experiment_only": sensitivity,
        "business_weights_changed": False,
        "quality_filter_recommendation": "Compare same factors and size_basis; coverage >=0.8",
        "bounds_interpretation": "Unknown factors in [0,1]; bounds are not confidence intervals",
    }


def nlp_diagnostics(data, config):
    projects = data["projects"]
    catalog = load_catalog()
    ranker = SemanticRanker(catalog, config)
    texts = ["\n".join(p.get(k) or "" for k in ("title", "description")).strip() for p in projects]
    with RuntimeMeasurement() as memory:
        start = perf_counter()
        ranker._model()
        model_load = perf_counter() - start
        start = perf_counter()
        similarities = ranker.rank_batch(texts)
        encode_seconds = perf_counter() - start
        baseline_engine, hybrid_engine = HybridRecommender(), HybridRecommender(ranker)
        start = perf_counter()
        baseline = baseline_engine.predict_batch(projects)
        baseline_seconds = perf_counter() - start

        # Повторное использование измеренных similarities не дублирует дорогой encode.
        class CachedRanker:
            def __init__(self):
                self.config, self.model_version = ranker.config, ranker.model_version

            def rank_batch(self, _):
                return similarities

        hybrid_engine.ranker = CachedRanker()
        start = perf_counter()
        hybrid = hybrid_engine.predict_batch(projects)
        combine_seconds = perf_counter() - start
        latency = {"baseline": [], "hybrid": []}
        hybrid_engine.ranker = ranker
        for project in projects:
            for method, engine in (("baseline", baseline_engine), ("hybrid", hybrid_engine)):
                start = perf_counter()
                engine.predict_batch([project])
                latency[method].append((perf_counter() - start) * 1000)
    changes, blocks = [], Counter()
    eligible = []
    for project, text, bs, hs, similarities_row in zip(
        projects, texts, baseline, hybrid, similarities, strict=True
    ):
        explicit, negated = explicit_and_blocked(text, catalog)
        found = {p.category for p in explicit}
        allowed = {c for s in matching_scenarios(text, catalog) for c in s["needs"]}
        for category, similarity in similarities_row.items():
            if category in allowed and category not in found | negated:
                eligible.append((project["external_id"], similarity))
            reason = (
                "already_explicit"
                if category in found
                else "negative_context"
                if category in negated
                else "scenario_not_applicable"
                if category not in allowed
                else "below_threshold"
                if similarity < config.threshold
                else "semantic_candidate"
            )
            blocks[reason] += 1
        bcat, hcat = [p.category for p in bs], [p.category for p in hs]
        if bcat != hcat:
            changes.append(
                {
                    "project_id": project["external_id"],
                    "baseline": bcat,
                    "hybrid": hcat,
                    "added": sorted(set(hcat) - set(bcat)),
                    "removed": sorted(set(bcat) - set(hcat)),
                    "order_only": set(bcat) == set(hcat),
                }
            )
    all_similarities = [v for row in similarities for v in row.values()]
    report = {
        "projects": len(projects),
        "model_revision": ranker.resolved_revision,
        "model_version": ranker.model_version,
        "threshold": config.threshold,
        "model_load_including_import_seconds": model_load,
        "encode_batch_seconds": encode_seconds,
        "baseline_batch_seconds": baseline_seconds,
        "hybrid_combination_seconds": combine_seconds,
        "hybrid_warm_batch_seconds": encode_seconds + combine_seconds,
        "latency_ms": {k: distribution(v) for k, v in latency.items()},
        "runtime": memory.result,
        "similarity_all": distribution(all_similarities),
        "similarity_by_category": {
            c: distribution([row[c] for row in similarities]) for c in catalog["categories"]
        },
        "candidate_decisions": dict(blocks),
        "eligible_similarity": distribution([v for _, v in eligible]),
        "threshold_what_if_not_tuned": {
            str(t): {
                "candidate_pairs": sum(v >= t for _, v in eligible),
                "projects_with_candidates": len({pid for pid, v in eligible if v >= t}),
            }
            for t in (0.78, 0.80, 0.82, 0.84, 0.86)
        },
        "project_similarities": [
            {"project_id": p["external_id"], "similarities": row}
            for p, row in zip(projects, similarities, strict=True)
        ],
        "changed_projects": changes,
        "passages": ranker._passages(),
        "unit_norms": distribution(np.linalg.norm(ranker._catalog_vectors, axis=1)),
        "accepted_semantic": sum(p.semantic_similarity is not None for ps in hybrid for p in ps),
        "baseline_categories": dict(
            Counter(p.category for ps in baseline for p in ps if p.category != UNKNOWN)
        ),
        "hybrid_categories": dict(
            Counter(p.category for ps in hybrid for p in ps if p.category != UNKNOWN)
        ),
        "baseline_abstentions": sum(ps[0].category == UNKNOWN for ps in baseline),
        "hybrid_abstentions": sum(ps[0].category == UNKNOWN for ps in hybrid),
        "quality_metrics": "not_evaluated: independent expert labels absent",
        "threshold_changed": False,
        "default_algorithm_recommendation": "rules; E5 optional pending expert evaluation",
    }
    outputs = []
    for predictions in (baseline, hybrid):
        outputs.append(
            {
                **data,
                "projects": [
                    {**p, "recommendations": [n.as_dict() for n in ns]}
                    for p, ns in zip(projects, predictions, strict=True)
                ],
            }
        )
    return report, outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-path")
    parser.add_argument("--revision", default="main")
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "scoring-diagnostics.json").write_text(
        json.dumps(scoring_diagnostics(data), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if args.model_path:
        report, outputs = nlp_diagnostics(
            data, EmbeddingConfig(model_path=args.model_path, revision=args.revision)
        )
        (args.output / "nlp-diagnostics.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        for method, output in zip(("baseline", "hybrid"), outputs, strict=True):
            (args.output / f"{method}.json").write_text(
                json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
            )


if __name__ == "__main__":
    main()
