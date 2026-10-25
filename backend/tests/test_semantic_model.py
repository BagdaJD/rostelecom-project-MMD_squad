"""Реальная E5 проверяется при явно указанном локальном пути; скачивания в тестах нет."""

import os

import numpy as np
import pytest

from ml.embeddings import EmbeddingConfig, ModelUnavailable, SemanticRanker
from ml.needs import load_catalog


def test_real_e5_cpu_inference(tmp_path):
    path = os.environ.get("MMD_E5_MODEL_PATH")
    if not path:
        pytest.skip("MMD_E5_MODEL_PATH не задан: реальная E5 не подменяется тестовым encoder")
    ranker = SemanticRanker(
        load_catalog(),
        EmbeddingConfig(
            model_path=path,
            revision=os.environ.get("MMD_E5_REVISION", "main"),
            cache_dir=str(tmp_path),
        ),
    )
    try:
        result = ranker.rank_batch(["Подключение склада к интернету", "Серверы и ЦОД"])
    except ModelUnavailable as exc:
        pytest.fail(str(exc))
    assert len(result) == 2 and all(len(row) == 5 for row in result)
    assert all(-1 <= value <= 1 for row in result for value in row.values())
    assert np.allclose(np.linalg.norm(ranker._catalog_vectors, axis=1), 1, atol=1e-5)
