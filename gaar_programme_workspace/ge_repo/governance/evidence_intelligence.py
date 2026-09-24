"""Evidence Intelligence: bi-encoder candidate retrieval, cross-encoder reranking and a
calibrated sufficiency-gate contract.

This module is deliberately optional at runtime.  The existing deterministic BM25 path remains
available when Ollama embeddings or sentence-transformers are unavailable.  Enabling the richer
path is controlled by environment variables so the live reviewer can be patched independently
from model downloads.

No score in this module is a governance decision.  Retrieval scores are evidence-selection
signals only; sufficiency thresholds must be calibrated against a labelled evaluation set before
being used as an enforcing gate.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import os
from typing import Any, Iterable, Sequence

DEFAULT_CROSS_ENCODER_MODEL = os.environ.get(
    "WB_CROSS_ENCODER_MODEL", "cross-encoder/ms-marco-MiniLM-L6-v2"
)


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class RerankScore:
    index: int
    score: float


class RerankerUnavailable(RuntimeError):
    """Cross-encoder reranking was requested but the optional backend is unavailable."""


class CrossEncoderReranker:
    """Lazy adapter for sentence-transformers CrossEncoder.

    The model is loaded only on the first rerank call, so importing the engine does not download
    a model and the current Colibri workflow remains independent of this feature.
    """

    def __init__(self, model_name: str = DEFAULT_CROSS_ENCODER_MODEL, *, local_files_only: bool | None = None):
        self.model_name = model_name
        self.local_files_only = env_bool("WB_CROSS_ENCODER_LOCAL_ONLY", False) if local_files_only is None else local_files_only
        self._model: Any | None = None
        self.status = "not_loaded"

    def _load(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import CrossEncoder
        except Exception as exc:  # pragma: no cover - environment dependent
            self.status = "unavailable"
            raise RerankerUnavailable(
                "sentence-transformers is not installed; install requirements-retrieval.txt "
                "before enabling cross-encoder reranking"
            ) from exc

        kwargs: dict[str, Any] = {"local_files_only": self.local_files_only}
        # MS-MARCO CrossEncoders expose logits. Sigmoid makes the diagnostic score bounded,
        # while leaving ranking unchanged. If a different model supplies a custom activation,
        # operators can override it later through the adapter.
        try:
            import torch
            kwargs["activation_fn"] = torch.nn.Sigmoid()
        except Exception:
            pass
        try:
            self._model = CrossEncoder(self.model_name, **kwargs)
        except Exception as exc:  # pragma: no cover - model/cache dependent
            self.status = "unavailable"
            raise RerankerUnavailable(
                f"cross-encoder model '{self.model_name}' could not be loaded: {exc}"
            ) from exc
        self.status = "ready"
        return self._model

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        if not passages:
            return []
        model = self._load()
        pairs = [[query, text] for text in passages]
        try:
            raw = model.predict(pairs)
        except Exception as exc:  # pragma: no cover - model/runtime dependent
            self.status = "error"
            raise RerankerUnavailable(f"cross-encoder inference failed: {exc}") from exc
        return [float(x) for x in raw]

    def rank(self, query: str, passages: Sequence[str]) -> list[RerankScore]:
        scores = self.score(query, passages)
        ranked = sorted((RerankScore(i, s) for i, s in enumerate(scores)), key=lambda x: (-x.score, x.index))
        return ranked


@dataclass(frozen=True)
class SufficiencyPolicy:
    """Configurable structural policy; numeric relevance thresholds require calibration."""

    min_candidates: int = 1
    min_cross_score: float | None = None
    min_bi_cosine: float | None = None
    require_calibrated_threshold: bool = False


@dataclass(frozen=True)
class SufficiencyResult:
    status: str
    reason: str
    candidate_count: int
    top_cross_score: float | None
    top_bi_cosine: float | None
    policy: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "candidate_count": self.candidate_count,
            "top_cross_score": self.top_cross_score,
            "top_bi_cosine": self.top_bi_cosine,
            "policy": dict(self.policy),
        }


class SufficiencyGate:
    """Evidence-selection gate, intentionally separate from governance judgement.

    In the initial implementation the gate can enforce structural requirements (for example,
    at least one retrieved candidate) but refuses to pretend that an uncalibrated model score is
    a universal sufficiency threshold.
    """

    def __init__(self, policy: SufficiencyPolicy | None = None):
        self.policy = policy or SufficiencyPolicy(
            min_candidates=int(os.environ.get("WB_EVIDENCE_MIN_CANDIDATES", "1")),
            min_cross_score=(float(os.environ["WB_EVIDENCE_MIN_CROSS_SCORE"])
                             if os.environ.get("WB_EVIDENCE_MIN_CROSS_SCORE") else None),
            min_bi_cosine=(float(os.environ["WB_EVIDENCE_MIN_BI_COSINE"])
                           if os.environ.get("WB_EVIDENCE_MIN_BI_COSINE") else None),
            require_calibrated_threshold=env_bool("WB_EVIDENCE_REQUIRE_CALIBRATED_THRESHOLD", False),
        )

    def evaluate(self, matches: Iterable[Any]) -> SufficiencyResult:
        rows = list(matches)
        candidate_count = len(rows)
        cross = [getattr(r, "cross_score", None) for r in rows]
        cross = [float(x) for x in cross if x is not None]
        bi = [getattr(r, "bi_cosine", None) for r in rows]
        bi = [float(x) for x in bi if x is not None]
        top_cross = max(cross) if cross else None
        top_bi = max(bi) if bi else None
        p = asdict(self.policy)

        if candidate_count < self.policy.min_candidates:
            return SufficiencyResult(
                status="BLOCKED",
                reason=f"Only {candidate_count} retrieval candidate(s); minimum is {self.policy.min_candidates}.",
                candidate_count=candidate_count,
                top_cross_score=top_cross,
                top_bi_cosine=top_bi,
                policy=p,
            )
        if self.policy.min_cross_score is not None and (top_cross is None or top_cross < self.policy.min_cross_score):
            return SufficiencyResult(
                status="BLOCKED",
                reason=(f"Cross-encoder evidence score {top_cross!r} is below the configured "
                        f"threshold {self.policy.min_cross_score!r}."),
                candidate_count=candidate_count,
                top_cross_score=top_cross,
                top_bi_cosine=top_bi,
                policy=p,
            )
        if self.policy.min_bi_cosine is not None and (top_bi is None or top_bi < self.policy.min_bi_cosine):
            return SufficiencyResult(
                status="BLOCKED",
                reason=(f"Bi-encoder cosine {top_bi!r} is below the configured threshold "
                        f"{self.policy.min_bi_cosine!r}."),
                candidate_count=candidate_count,
                top_cross_score=top_cross,
                top_bi_cosine=top_bi,
                policy=p,
            )
        if self.policy.require_calibrated_threshold and self.policy.min_cross_score is None and self.policy.min_bi_cosine is None:
            return SufficiencyResult(
                status="CALIBRATION_REQUIRED",
                reason="No calibrated numeric relevance threshold is configured.",
                candidate_count=candidate_count,
                top_cross_score=top_cross,
                top_bi_cosine=top_bi,
                policy=p,
            )
        return SufficiencyResult(
            status="PASS",
            reason="Evidence retrieval satisfied the configured structural/calibrated policy.",
            candidate_count=candidate_count,
            top_cross_score=top_cross,
            top_bi_cosine=top_bi,
            policy=p,
        )
