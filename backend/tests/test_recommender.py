import numpy as np
import pytest

from ml.embeddings import EmbeddingConfig, ModelUnavailable, SemanticRanker, normalize_vectors
from ml.evaluation import annotation_template, evaluate
from ml.needs import UNKNOWN, classify_need, load_catalog
from ml.recommender import HybridRecommender


def test_explicit_evidence_preserves_case_and_unicode():
    text = "Новый объект: Видеонаблюдение, СЕРВЕРЫ и VPN."
    predictions = classify_need(text)
    assert len(predictions) == 3
    for p in predictions:
        assert p.evidence_type == "explicit" and p.evidence in text
        assert p.probability is None and p.confidence_label == "high"


def test_inferred_has_no_fake_quote():
    predictions = classify_need("Строительство комбикормового цеха")
    assert {p.category for p in predictions} == {"iot_asu_tp", "connectivity", "video_surveillance"}
    assert all(
        p.evidence_type == "inferred" and p.evidence is None and p.reason for p in predictions
    )


@pytest.mark.parametrize(
    "text",
    [
        "Информационный стенд и техника безопасности",
        "Распродажа канцтоваров",
        "Средняя величина и план",
        "",
        "Холодильные камеры для заморозки",
        "Камера сгорания двигателя",
        "Видеонаблюдение не предусмотрено",
        "Не требуется видеонаблюдение",
        "Без видеонаблюдения",
    ],
)
def test_generic_irrelevant_and_negative_abstain(text):
    assert classify_need(text)[0].category == UNKNOWN


def test_negative_context_does_not_block_other_clause():
    predictions = classify_need("Без видеонаблюдения, но требуются серверы")
    assert [p.category for p in predictions] == ["it_infrastructure"]
    predictions = classify_need("Завод без видеонаблюдения")
    assert "video_surveillance" not in {p.category for p in predictions}


def test_vector_normalization_finite_zero_and_shape():
    vectors = normalize_vectors([[3, 4], [0, 0]])
    assert np.linalg.norm(vectors[0]) == pytest.approx(1)
    assert np.isfinite(vectors).all() and vectors[1].tolist() == [0, 0]
    with pytest.raises(ValueError):
        normalize_vectors([[np.nan]])
    with pytest.raises(ValueError):
        normalize_vectors([1, 2])


def test_model_version_does_not_depend_on_cache_location(tmp_path):
    a = SemanticRanker(
        load_catalog(), EmbeddingConfig(model_path="location-a", cache_dir=str(tmp_path / "a"))
    )
    b = SemanticRanker(
        load_catalog(), EmbeddingConfig(model_path="location-b", cache_dir=str(tmp_path / "b"))
    )
    assert a.model_version == b.model_version


class TinyEncoder:
    """Явный test double только для проверки механики; не модель в production."""

    def __init__(self):
        self.calls = []

    def encode(self, texts, **kwargs):
        self.calls.append(texts)
        return np.array([[1, 0] for _ in texts], dtype=float)


def test_e5_prefix_batching_and_persistent_catalog_cache(tmp_path):
    encoder = TinyEncoder()
    config = EmbeddingConfig(cache_dir=str(tmp_path), batch_size=2)
    ranker = SemanticRanker(load_catalog(), config, encoder=encoder)
    output = ranker.rank_batch(["a", "b", "c"])
    assert len(output) == 3 and len(encoder.calls) == 3
    assert all(t.startswith("passage: ") for t in encoder.calls[0])
    assert all(t.startswith("query: ") for batch in encoder.calls[1:] for t in batch)
    again = TinyEncoder()
    SemanticRanker(load_catalog(), config, encoder=again).rank_batch(["a"])
    assert len(again.calls) == 1 and again.calls[0][0].startswith("query:")


def test_threshold_and_applicability_prevent_semantic_hallucination(tmp_path):
    ranker = SemanticRanker(
        load_catalog(), EmbeddingConfig(cache_dir=str(tmp_path)), encoder=TinyEncoder()
    )
    result = HybridRecommender(ranker).predict_batch([{"title": "Канцелярские товары"}])[0]
    assert result[0].category == UNKNOWN
    result = HybridRecommender(ranker).predict_batch([{"title": "Завод без видеонаблюдения"}])[0]
    assert "video_surveillance" not in {p.category for p in result}
    assert len(result) <= 3


def test_model_unavailability_uses_explicit_baseline(monkeypatch):
    ranker = SemanticRanker(load_catalog())

    def unavailable(texts):
        raise ModelUnavailable("test: нет локальной модели")

    monkeypatch.setattr(ranker, "rank_batch", unavailable)
    recommender = HybridRecommender(ranker)
    result = recommender.predict_batch([{"title": "Нужны серверы"}])[0]
    assert result[0].category == "it_infrastructure"
    assert "нет локальной модели" in recommender.semantic_status


def test_empty_gold_is_not_evaluated():
    gold = annotation_template([{"external_id": "1", "title": "Объект"}])
    assert evaluate(gold, {})["status"] == "not_evaluated"


def test_rescoring_preserves_saved_nlp_without_inference(monkeypatch):
    from datetime import date

    from ingestion.pipeline import analyze

    saved = {
        "source": "test",
        "external_id": "p1",
        "title": "Завод",
        "recommendations": [p.as_dict() for p in classify_need("Нужны серверы")],
    }

    def forbidden(projects):
        raise AssertionError("Повторный NLP при пересчёте рейтинга")

    recommender = HybridRecommender()
    monkeypatch.setattr(recommender, "predict_batch", forbidden)
    result = analyze(
        [], [saved], as_of=date(2026, 10, 24), recommender=recommender, reuse_recommendations=True
    )
    assert result["projects"][0]["recommendations"] == saved["recommendations"]


def test_metrics_require_manual_evidence_and_explicit_inferred_separation():
    text = "VPN для завода"
    predictions = {"1": [p.as_dict() for p in classify_need(text)]}
    gold = {
        "projects": [
            {
                "project_id": "1",
                "split": "test",
                "text": text,
                "explicit_categories": ["connectivity"],
                "explicit_evidence": {"connectivity": "VPN"},
                "inferred_relevant": {"iot_asu_tp": True, "video_surveillance": False},
            }
        ]
    }
    result = evaluate(gold, predictions)
    assert result["per_category"]["connectivity"]["f1"] == 1
    assert result["inferred_precision_at_3"] == pytest.approx(1 / 3)
    gold["projects"][0]["explicit_evidence"] = {}
    with pytest.raises(ValueError, match="цитату"):
        evaluate(gold, predictions)
