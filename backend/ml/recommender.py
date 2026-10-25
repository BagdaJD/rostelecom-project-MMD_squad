"""Гибрид: явные правила приоритетны, семантика ранжирует допустимые гипотезы."""

from dataclasses import replace

from ml.embeddings import ModelUnavailable, SemanticRanker
from ml.needs import (
    UNKNOWN,
    NeedPrediction,
    classify_need,
    explicit_and_blocked,
    load_catalog,
    matching_scenarios,
)


class HybridRecommender:
    def __init__(self, ranker: SemanticRanker | None = None, catalog_path=None):
        self.catalog_path = catalog_path
        self.catalog = load_catalog(catalog_path)
        self.ranker = ranker
        self.semantic_status = "disabled" if ranker is None else "pending"
        self._unavailable = False

    def predict_batch(self, projects: list[dict]) -> list[list[NeedPrediction]]:
        texts = [
            "\n".join(p.get(k) or "" for k in ("title", "description")).strip() for p in projects
        ]
        similarities = [None] * len(texts)
        if self.ranker and not self._unavailable:
            try:
                similarities = self.ranker.rank_batch(texts)
                self.semantic_status = "available"
            except ModelUnavailable as exc:
                self.semantic_status = str(exc)
                self._unavailable = True
        results = []
        for project, text, scores in zip(projects, texts, similarities, strict=True):
            if scores is None:
                results.append(
                    classify_need(
                        project.get("title", ""),
                        project.get("description"),
                        catalog_path=self.catalog_path,
                    )
                )
                continue
            explicit, blocked = explicit_and_blocked(text, self.catalog)
            found = {p.category for p in explicit}
            allowed = {c for s in matching_scenarios(text, self.catalog) for c in s["needs"]}
            inferred = []
            for category, similarity in sorted(scores.items(), key=lambda kv: -kv[1]):
                if category not in allowed or category in found | blocked:
                    continue
                if similarity < self.ranker.config.threshold:
                    continue
                inferred.append(
                    NeedPrediction(
                        category,
                        evidence_type="inferred",
                        rule_id="inferred:semantic",
                        reason=self.catalog["categories"][category]["reason"],
                        semantic_similarity=round(similarity, 6),
                        confidence_label="low",
                        model_version=self.ranker.model_version,
                    )
                )
            baseline = classify_need(
                project.get("title", ""), project.get("description"), catalog_path=self.catalog_path
            )
            selected = [*explicit, *inferred]
            selected_categories = {p.category for p in selected}
            selected.extend(
                p
                for p in baseline
                if p.evidence_type == "inferred" and p.category not in selected_categories
            )
            results.append(
                [replace(p, model_version=self.ranker.model_version) for p in selected[:3]]
                or [
                    NeedPrediction(
                        UNKNOWN,
                        model_version=self.ranker.model_version,
                        data_quality="insufficient",
                    )
                ]
            )
        return results
