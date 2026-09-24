from __future__ import annotations

from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _control():
    return types.SimpleNamespace(
        title="Independent validation scope",
        req="Independent validation must cover the applicable scope and evidence.",
        maps="validation scope evidence",
        id="M3.6",
    )


def test_sufficiency_gate_structural_pass_and_empty_block():
    from governance.evidence_intelligence import SufficiencyGate, SufficiencyPolicy, SufficiencyResult

    gate = SufficiencyGate(SufficiencyPolicy(min_candidates=1))
    blocked = gate.evaluate([])
    assert blocked.status == "BLOCKED"

    row = types.SimpleNamespace(cross_score=None, bi_cosine=None)
    passed = gate.evaluate([row])
    assert passed.status == "PASS"


def test_sufficiency_gate_requires_calibration_when_policy_demands_it():
    from governance.evidence_intelligence import SufficiencyGate, SufficiencyPolicy

    gate = SufficiencyGate(SufficiencyPolicy(min_candidates=1, require_calibrated_threshold=True))
    row = types.SimpleNamespace(cross_score=0.91, bi_cosine=0.8)
    result = gate.evaluate([row])
    assert result.status == "CALIBRATION_REQUIRED"


def test_cross_encoder_adapter_is_lazy_and_ranked(monkeypatch):
    import governance.evidence_intelligence as ei

    class FakeCrossEncoder:
        def __init__(self, model_name_or_path, **kwargs):
            self.model_name_or_path = model_name_or_path

        def predict(self, pairs):
            # The second passage is intentionally more relevant.
            return [0.10, 0.90, 0.40][:len(pairs)]

    fake_st = types.SimpleNamespace(CrossEncoder=FakeCrossEncoder)
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_st)

    reranker = ei.CrossEncoderReranker("fake-model", local_files_only=True)
    assert reranker.status == "not_loaded"
    ranked = reranker.rank("scope", ["generic text", "independent validation scope", "unrelated"])
    assert ranked[0].index == 1
    assert ranked[0].score == 0.90
    assert reranker.status == "ready"


def test_index_can_rerank_without_changing_legacy_tuple_shape(monkeypatch):
    import scanner
    import governance.evidence_intelligence as ei

    class FakeCrossEncoder:
        def __init__(self, model_name_or_path, **kwargs):
            pass

        def predict(self, pairs):
            # The operating-evidence passage should rerank above the more lexical match.
            return [0.95 if "operating evidence" in pair[1] else 0.20 for pair in pairs]

    monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(CrossEncoder=FakeCrossEncoder))
    monkeypatch.setenv("WB_EVIDENCE_CROSS_ENCODER", "1")
    monkeypatch.setenv("WB_EVIDENCE_BI_ENCODER", "0")

    chunks = [
        scanner.Chunk("a.txt", "independent validation scope control evidence", 0),
        scanner.Chunk("b.txt", "independent validation scope and operating evidence", 0),
    ]
    index = scanner.Index(chunks, use_embeddings=False, use_reranker=True, rerank_k=2)
    hits = index.query(_control(), k=2, min_ratio=0.0)
    assert len(hits) == 2
    assert hits[0][0].path == "b.txt"
    assert hits[0].cross_score == 0.95
    assert "cross_encoder" in index.last_query_receipt
    assert hits[0].retrieval_methods == ["bm25"]


def test_exact_control_evidence_stays_first_after_cross_encoder(monkeypatch):
    import scanner

    class FakeCrossEncoder:
        def __init__(self, model_name_or_path, **kwargs):
            pass
        def predict(self, pairs):
            return [0.05 if "exact artefact" in pair[1] else 0.99 for pair in pairs]

    monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(CrossEncoder=FakeCrossEncoder))
    control = types.SimpleNamespace(
        title="Independent validation", req="validation scope methods thresholds",
        maps="testing", id="M3.6", lib="MAS")
    chunks = [
        scanner.Chunk("/evidence/MAS/M3.6_Evaluation.md", "exact artefact validation scope", 0),
        scanner.Chunk("/evidence/MAS/M2.4_Risk.md", "cross control validation scope methods thresholds", 0),
    ]
    index = scanner.Index(chunks, use_embeddings=False, use_reranker=True, rerank_k=2)
    hits = index.query(control, k=2, min_ratio=0.0)
    assert hits[0].chunk.path.endswith("M3.6_Evaluation.md")
    assert hits[0].identity_tier == "EXACT_CONTROL"
    assert hits[1].identity_tier == "SAME_FRAMEWORK_SUPPLEMENT"
    assert index.last_query_receipt['identity_policy']=='exact-control-first-v1'


def test_build_evidence_persists_retrieval_receipt():
    from pipeline import build_evidence
    import scanner

    c = _control()
    row = scanner.EvidenceMatch(
        scanner.Chunk("evidence.md", "Independent validation evidence.", 0),
        score=4.2,
        bm25_score=4.2,
        bi_cosine=0.81,
        cross_score=0.93,
        retrieval_methods=["bm25", "bi_encoder"],
        reranker_model="test-model",
    )
    out = build_evidence(c, [row], [])
    assert out["retrieval"]["schema"] == "evidence-intelligence.1"
    assert out["retrieval"]["matches"][0]["cross_score"] == 0.93
    assert out["retrieval"]["sufficiency"]["status"] == "PASS"
