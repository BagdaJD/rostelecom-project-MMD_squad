"""Ленивый CPU E5: локальная модель, пакетный encode, кеш каталога по hash."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np


class ModelUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class EmbeddingConfig:
    model_name: str = "intfloat/multilingual-e5-small"
    revision: str = "main"
    model_path: str | None = None
    batch_size: int = 8
    max_length: int = 512
    threads: int = 2
    threshold: float = 0.84
    cache_dir: str = str(Path(__file__).with_name("artifacts") / "embeddings")

    def __post_init__(self):
        if not 0 <= self.threshold <= 1 or min(self.batch_size, self.max_length, self.threads) < 1:
            raise ValueError("Некорректная конфигурация embeddings")


def normalize_vectors(vectors) -> np.ndarray:
    array = np.asarray(vectors, dtype=np.float32)
    if array.ndim != 2 or not np.isfinite(array).all():
        raise ValueError("Ожидается конечная двумерная матрица")
    lengths = np.linalg.norm(array, axis=1, keepdims=True)
    return np.divide(array, lengths, out=np.zeros_like(array), where=lengths != 0)


class SemanticRanker:
    def __init__(self, catalog: dict, config: EmbeddingConfig | None = None, *, encoder=None):
        self.catalog = catalog
        self.config = config or EmbeddingConfig()
        self.encoder = encoder
        self.categories = list(catalog["categories"])
        self._catalog_vectors = None
        self.resolved_revision = self.config.revision

    @property
    def model_version(self):
        semantic_config = asdict(self.config)
        # Размещение файлов не меняет модель и не должно менять идентификатор результата.
        semantic_config.pop("cache_dir")
        semantic_config.pop("model_path")
        identity = {
            **semantic_config,
            "revision": self.resolved_revision,
            "catalog": self.catalog["model_version"],
        }
        return (
            "e5-" + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
        )

    def _model(self):
        if self.encoder is None:
            try:
                import torch
                from sentence_transformers import SentenceTransformer

                torch.set_num_threads(self.config.threads)
                self.encoder = SentenceTransformer(
                    self.config.model_path or self.config.model_name,
                    revision=self.config.revision,
                    device="cpu",
                    local_files_only=True,
                    trust_remote_code=False,
                )
                self.encoder.max_seq_length = self.config.max_length
                self.resolved_revision = (
                    getattr(self.encoder[0].auto_model.config, "_commit_hash", None)
                    or self.config.revision
                )
                if self.config.model_path:
                    metadata = (
                        Path(self.config.model_path)
                        / ".cache/huggingface/download/config.json.metadata"
                    )
                    if metadata.is_file():
                        self.resolved_revision = metadata.read_text(encoding="utf-8").splitlines()[
                            0
                        ]
            except (ImportError, OSError, RuntimeError, ValueError) as exc:
                raise ModelUnavailable(f"E5 недоступна локально ({type(exc).__name__})") from exc
        return self.encoder

    def _encode(self, texts):
        return normalize_vectors(
            self._model().encode(
                texts,
                batch_size=self.config.batch_size,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        )

    def _passages(self):
        return [
            "passage: "
            + self.catalog["categories"][category]["description"]
            + " Сценарии: "
            + ", ".join(s["id"] for s in self.catalog["scenarios"] if category in s["needs"])
            for category in self.categories
        ]

    def rank_batch(self, texts: list[str]) -> list[dict[str, float]]:
        if not texts:
            return []
        self._model()
        if self._catalog_vectors is None:
            passages = self._passages()
            key = hashlib.sha256((self.model_version + json.dumps(passages)).encode()).hexdigest()
            cache = Path(self.config.cache_dir)
            cache.mkdir(parents=True, exist_ok=True)
            target = cache / f"{key}.npy"
            if target.exists():
                try:
                    vectors = np.load(target, allow_pickle=False)
                    if vectors.shape[0] != len(passages):
                        raise ValueError("Invalid cache shape")
                    self._catalog_vectors = normalize_vectors(vectors)
                except (OSError, ValueError):
                    self._catalog_vectors = None
            if self._catalog_vectors is None:
                self._catalog_vectors = self._encode(passages)
                np.save(target, self._catalog_vectors, allow_pickle=False)
        output = []
        for start in range(0, len(texts), self.config.batch_size):
            queries = [
                "query: " + re.sub(r"\s+", " ", t).strip()
                for t in texts[start : start + self.config.batch_size]
            ]
            vectors = self._encode(queries)
            scores = np.clip(vectors @ self._catalog_vectors.T, -1, 1)
            output.extend(
                dict(zip(self.categories, map(float, row), strict=True)) for row in scores
            )
        return output
