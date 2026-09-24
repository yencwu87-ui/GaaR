"""Scan local folders for evidence and map it to controls.

Two scans:
  scan_documents(folder) -> list of Chunk   (pdf, docx, xlsx, md, txt, csv, json, yaml)
  scan_environment(folder) -> list of Signal (config/code artefacts that hint at a control)
Then retrieve(chunks, control) -> top chunks for a control, BM25-ranked.
Everything runs locally; nothing is sent anywhere until assess() is called.
"""
# sample_evidence/ holds fixture data used to test the controls themselves. Scanning it
# produced findings against a critical control (DISC-01) that could only be cleared by a
# permanent exception — a fixture is not an exposure. evidence/ holds past bundles, which
# are outputs of the scan, not inputs to it.


import fnmatch
import io
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

DOC_EXT = {".pdf", ".docx", ".xlsx", ".md", ".txt", ".csv", ".json", ".yaml", ".yml", ".log"}
# sample_evidence/ holds fixture data used to test the controls themselves. Scanning it
# produced findings against a critical control (DISC-01) that could only be cleared by a
# permanent exception — a fixture is not an exposure. evidence/ holds past bundles, which
# are outputs of the scan, not inputs to it.
#
# WB-021: data/, graphify-out/ and .cache/ hold the workbench's own state and outputs — the
# playbook workbook, assessments.json and its dated backups, the write-back copies. Scanning
# them fed the control register back to the assessor as evidence: stored proposals rated
# controls off register rows describing other controls, and each scan ingested the previous
# scan's output. Matched by path relative to the scan root (see _skipped), so naming one of
# these as the folder to scan still works.
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".idea", ".vscode",
             "site-packages", "sample_evidence", "evidence",
             "data", "backups", "graphify-out", ".cache"}

# Output artefacts that may be written outside those directories.
SKIP_FILE_GLOBS = ("playbook_assessed_*.xlsx", "assessments*.json", "*.bak", ".demo_manifest.json")
MAX_FILE_MB = 25
CHUNK = 1800
OVERLAP = 200

# ---------------------------------------------------------------------------
# Self-scan guard (WB-0nn)
#
# WB-021 added data/ and friends to SKIP_DIRS and that fix was real, but it
# assumed the scan root was somebody's evidence folder that happened to contain
# the workbench's state. It was not. A run against
#   /Users/.../ai-governance-readiness-workbench/
# indexed the workbench itself: requirements/mas.yaml was the single most cited
# evidence source at 69 records of 85, so the assessor was reading the control
# definitions and grading them as the organisation's evidence. eval/corpus/
# documents appeared in 38 records, putting the held-out measurement set into
# the model's context, and stress/h02_injection.json put the injection fixtures
# there too. 77 of 85 evidence records cited the tool's own files.
#
# The lesson is that a skip list cannot fix this, because a skip list is a list
# of directories somebody remembered. requirements/, eval/, stress/, caa/,
# policy/ and docs/ were all absent from it, and adding them would break any
# client folder that legitimately has a directory of that name — ENV_RULES
# already treats requirements*.txt as a signal worth finding.
#
# So the unit of exclusion is the installation, not the directory name. Any
# directory carrying the workbench's marker files is pruned wherever it is
# found, which covers a second checkout sitting inside a client folder. And a
# scan root that contains the running installation is refused outright rather
# than quietly returning whatever is left, because a near-empty scan reads as
# "no evidence exists" — a finding — when the truth is that the scan was
# pointed at the wrong place.
# ---------------------------------------------------------------------------
SELF_ROOT = Path(__file__).resolve().parent
WORKBENCH_MARKERS = {"app.py", "assessor.py", "pipeline.py", "scanner.py", "playbook.py"}
MARKERS_REQUIRED = 4


class SelfScanError(RuntimeError):
    """The scan root is, or contains, the workbench installation itself."""


def _is_workbench_dir(p: Path) -> bool:
    """True if this directory looks like a workbench installation."""
    try:
        names = {e.name for e in os.scandir(p) if e.is_file()}
    except OSError:
        return False
    return len(WORKBENCH_MARKERS & names) >= MARKERS_REQUIRED


def self_scan_reason(folder: str) -> str | None:
    """Why this root must not be scanned, or None if it is fine.

    Returns a sentence for the reviewer, not a code. The person who pointed the
    scanner at the wrong folder needs to know which folder and why, not that a
    boolean was False.
    """
    try:
        root = Path(folder).resolve()
    except OSError:
        return None
    if not root.is_dir():
        return None
    if root == SELF_ROOT:
        return ("This folder is the workbench itself. Scanning it indexes the control "
                "library, the evaluation corpus and the tool's own documentation as though "
                "they were the organisation's evidence.")
    if SELF_ROOT.is_relative_to(root):
        return (f"This folder contains the running workbench ({SELF_ROOT}). Scanning it "
                "indexes the control library and the evaluation corpus as evidence. Point "
                "the scan at the evidence folder instead.")
    if root.is_relative_to(SELF_ROOT):
        return ("This folder is inside the workbench installation. Its contents are the "
                "tool's own files, not evidence about an organisation.")
    return None


def _guard(folder: str, allow_self: bool) -> None:
    if allow_self:
        return
    reason = self_scan_reason(folder)
    if reason:
        raise SelfScanError(reason)


# Retrieval defaults. See eval/threshold_probe.py for how these were chosen.
# The old absolute min_score never bound: on a 195-control run the weakest
# control's top BM25 score was 16.6, so a slider capped well below that
# excluded nothing and every control received exactly k chunks regardless of
# relevance. BM25 scores are unbounded, corpus-relative, and scale with query
# length (correlation +0.86 between query terms and top score), so no single
# absolute number means the same thing across the five control libraries.
# MIN_RATIO thresholds relative to the best-scoring chunk for that control,
# which is corpus- and query-length independent. MIN_SCORE is a small absolute
# floor so that a control with no relevant evidence returns nothing rather than
# the three least-bad chunks in the folder.
MIN_RATIO = 0.35
MIN_SCORE = 0.0
TOP_K = 3


@dataclass
class Chunk:
    path: str
    text: str
    idx: int

    @property
    def label(self):
        return f"{Path(self.path).name} [part {self.idx + 1}]"


@dataclass
class EvidenceMatch:
    """Backward-compatible match object with auditable retrieval-stage metadata."""
    chunk: Chunk
    score: float
    bm25_score: float = 0.0
    bi_cosine: float | None = None
    cross_score: float | None = None
    retrieval_methods: list[str] = field(default_factory=list)
    reranker_model: str | None = None
    identity_tier: str = "UNCLASSIFIED"

    def __iter__(self):
        yield self.chunk
        yield self.score

    def __getitem__(self, idx):
        if idx == 0:
            return self.chunk
        if idx == 1:
            return self.score
        raise IndexError(idx)


@dataclass
class Signal:
    path: str
    kind: str
    hint: str
    controls: list


def _normalise_identity(value: str) -> str:
    return re.sub(r"[^A-Z0-9.]", "", str(value or "").upper())


def _path_identity(control, path: str) -> tuple[int, str]:
    """Prioritise evidence explicitly labelled for the queried control.

    Similarity still ranks documents within each tier.  Cross-control evidence remains
    visible as supplementary context but can no longer silently outrank an exact-control
    artefact merely because it shares domain vocabulary.
    """
    target_control = _normalise_identity(getattr(control, "id", ""))
    target_framework = _normalise_identity(getattr(control, "lib", ""))
    p = Path(path)
    name_match = re.match(r"(?i)^([A-Z]+\d+(?:[.]\d+)*)[_\s-]", p.name)
    detected_control = _normalise_identity(name_match.group(1) if name_match else "")
    detected_framework = ""
    for part in p.parts:
        normalised = _normalise_identity(part)
        if normalised in {"MAS", "SAFR", "MGFAGENTIC", "ISO42001", "NISTAIRMF"}:
            detected_framework = normalised
    if detected_control and detected_control == target_control and (
        not target_framework or not detected_framework or detected_framework == target_framework
    ):
        return 0, "EXACT_CONTROL"
    if target_framework and detected_framework == target_framework:
        return 1, "SAME_FRAMEWORK_SUPPLEMENT"
    if not detected_control and not detected_framework:
        return 2, "UNCLASSIFIED_SUPPLEMENT"
    return 3, "CROSS_CONTROL_SUPPLEMENT"


# ---------- text extraction ----------
def _pdf(p: Path) -> str:
    from pypdf import PdfReader
    r = PdfReader(str(p))
    return "\n".join((pg.extract_text() or "") for pg in r.pages)


def _docx(p: Path) -> str:
    import docx
    d = docx.Document(str(p))
    parts = [para.text for para in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            parts.append(" | ".join(c.text for c in row.cells))
    return "\n".join(parts)


def _xlsx(p: Path) -> str:
    from openpyxl import load_workbook
    wb = load_workbook(str(p), read_only=True, data_only=True)
    out = []
    for ws in wb.worksheets:
        out.append(f"## Sheet: {ws.title}")
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i > 2000:
                break
            vals = [str(v) for v in row if v is not None]
            if vals:
                out.append(" | ".join(vals))
    return "\n".join(out)


def extract(p: Path) -> str:
    ext = p.suffix.lower()
    try:
        if ext == ".pdf":
            return _pdf(p)
        if ext == ".docx":
            return _docx(p)
        if ext == ".xlsx":
            return _xlsx(p)
        return p.read_text(errors="ignore")
    except Exception as e:  # unreadable file is a finding, not a crash
        return f"[unreadable: {e}]"


def chunk_text(text: str) -> list[str]:
    text = re.sub(r"[ \t]+", " ", text)
    out, i = [], 0
    while i < len(text):
        out.append(text[i:i + CHUNK])
        i += CHUNK - OVERLAP
    return [c for c in out if c.strip()]


def _skipped(rel: Path, name: str) -> bool:
    """Skip decision for one path, taken relative to the scan root.

    Relative, not absolute: the previous check tested every component of the absolute path, so
    a folder whose own name was in SKIP_DIRS could never be scanned — pointing the scanner at
    sample_evidence/ returned nothing — and any client folder sitting under a path component
    called "data" or "evidence" was silently excluded.
    """
    return (any(part in SKIP_DIRS for part in rel.parts)
            or any(fnmatch.fnmatch(name, g) for g in SKIP_FILE_GLOBS))


def walk(folder: str, *, allow_self: bool = False):
    """Yield (path, relative_path) for every file under the scan root, pruned.

    os.walk rather than rglob so a skipped directory is not descended into. rglob
    visited every file inside .venv and node_modules and then discarded them, which
    was slow and, more to the point, meant a pruning rule could only ever be a
    filter — it could not stop a subtree being read at all.

    Pruned: SKIP_DIRS by name, and any directory carrying the workbench's marker
    files, so a checkout sitting inside an evidence folder is excluded as a unit
    rather than by guessing at its subdirectory names.
    """
    _guard(folder, allow_self)
    root = Path(folder).resolve()
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        keep = []
        for d in dirnames:
            if d in SKIP_DIRS:
                continue
            if not allow_self and _is_workbench_dir(here / d):
                continue
            keep.append(d)
        dirnames[:] = keep
        for fn in filenames:
            p = here / fn
            rel = p.relative_to(root)
            if _skipped(rel, fn):
                continue
            yield p, rel


def iter_files(folder: str, exts: set[str], *, allow_self: bool = False):
    for p, _rel in walk(folder, allow_self=allow_self):
        try:
            if p.suffix.lower() in exts and p.stat().st_size < MAX_FILE_MB * 1e6:
                yield p
        except OSError:
            continue


def scan_documents(folder: str, progress=None, *, allow_self: bool = False) -> list[Chunk]:
    chunks = []
    files = list(iter_files(folder, DOC_EXT, allow_self=allow_self))
    for n, p in enumerate(files):
        if progress:
            progress(n, len(files), p.name)
        for i, c in enumerate(chunk_text(f"[{p.name}]\n" + extract(p))):
            chunks.append(Chunk(str(p), c, i))
    return chunks


# ---------- environment signals ----------
# (glob, kind, hint, control ids that this artefact is relevant to)
ENV_RULES = [
    ("*.tf", "iac", "Infrastructure-as-code present — deployment is codified and reviewable", ["M3", "S3.1", "A.6"]),
    ("Dockerfile", "container", "Container build definition — check for pinned base images and non-root user", ["M3", "S3.1"]),
    ("docker-compose*.yml", "container", "Container orchestration config", ["M3"]),
    (".github/workflows/*.yml", "ci", "CI pipeline — check for tests, scans and approval gates before deploy", ["M3", "D3.2", "S3.2"]),
    ("*.gitlab-ci.yml", "ci", "CI pipeline — check for tests, scans and approval gates before deploy", ["M3", "D3.2", "S3.2"]),
    ("*model_card*", "model-doc", "Model card — documentation of intended use, limits and evaluation", ["D1.1", "M2", "A.6.2", "MAP 1.1"]),
    ("*MODEL_CARD*", "model-doc", "Model card — documentation of intended use, limits and evaluation", ["D1.1", "M2", "A.6.2"]),
    ("*eval*", "evaluation", "Evaluation artefacts — tests or golden sets for model behaviour", ["D3.1", "M4", "MEASURE 2"]),
    ("*test*", "evaluation", "Test artefacts", ["D3.1", "M4"]),
    ("*logging*", "logging", "Logging configuration — check what agent actions are captured and retained", ["S4.1", "D4.1", "M5"]),
    ("*log4j*", "logging", "Logging configuration", ["S4.1", "D4.1"]),
    ("*iam*", "access", "IAM/access policy — check least privilege for agent identities", ["S1.2", "S2.1", "D2.1"]),
    ("*rbac*", "access", "Role-based access config", ["S1.2", "D2.1"]),
    ("*.env", "secrets", "Environment file — secrets may be stored in plaintext; must not be in evidence or repos", ["S1.3", "D2.2"]),
    ("*secret*", "secrets", "Secrets-related file — verify it is a reference, not plaintext credentials", ["S1.3", "D2.2"]),
    ("*prompt*", "prompt", "Prompt/system-prompt files — governed as configuration? versioned? reviewed?", ["D2.3", "S2.2", "M2"]),
    ("*guardrail*", "guardrail", "Guardrail configuration — policy-bound execution evidence", ["S2.1", "D2.3"]),
    ("*policy*.json", "policy", "Machine-readable policy — check who can change it and how changes are reviewed", ["S2.1", "S1.1"]),
    ("*incident*", "incident", "Incident records or runbooks", ["D4.3", "S4.3", "M6"]),
    ("*runbook*", "incident", "Runbooks — operational response procedures", ["D4.3", "S4.3"]),
    ("*inventory*", "inventory", "Inventory register — agent/model registration evidence", ["S1.1", "M1.3", "A.9"]),
    ("*register*", "inventory", "Register document", ["S1.1", "M1.3"]),
    ("*dpia*", "privacy", "Data protection impact assessment", ["M2", "A.8"]),
    ("*pdpa*", "privacy", "PDPA-related document", ["M2", "A.8"]),
    ("requirements*.txt", "dependencies", "Python dependency manifest — third-party AI libraries and pinned versions", ["M3", "A.10"]),
    ("package.json", "dependencies", "Node dependency manifest", ["M3", "A.10"]),
    ("*sbom*", "dependencies", "Software bill of materials", ["M3", "A.10"]),
]


def scan_environment(folder: str, *, allow_self: bool = False) -> list[Signal]:
    out, seen = [], set()
    for p, relp in walk(folder, allow_self=allow_self):
        if p.name.lower().endswith((".example", ".template", ".sample")):
            continue
        rel = str(relp)
        for pat, kind, hint, ctls in ENV_RULES:
            if fnmatch.fnmatch(p.name.lower(), pat.lower()) or fnmatch.fnmatch(rel.lower(), pat.lower()):
                if (rel, kind) not in seen:
                    seen.add((rel, kind))
                    out.append(Signal(rel, kind, hint, ctls))
                break
    return out


# ---------- retrieval ----------
_tok = lambda s: re.findall(r"[a-z0-9][a-z0-9\-\.]{1,}", s.lower())


class _LexicalFallback:
    """Small deterministic BM25-compatible fallback used only when rank-bm25 is unavailable.

    It preserves the scanner contract and is deliberately conservative; the real
    rank-bm25 implementation is still preferred whenever the optional dependency exists.
    """
    def __init__(self, corpus_tokens):
        self.corpus = corpus_tokens
        self.n = len(corpus_tokens)
        df = {}
        for toks in corpus_tokens:
            for tok in set(toks):
                df[tok] = df.get(tok, 0) + 1
        import math
        self.idf = {t: math.log((self.n + 1) / (n + 1)) + 1.0 for t, n in df.items()}

    def get_scores(self, query_tokens):
        scores = []
        q = set(query_tokens)
        for toks in self.corpus:
            counts = {}
            for t in toks:
                counts[t] = counts.get(t, 0) + 1
            scores.append(float(sum(self.idf.get(t, 0.0) * min(counts.get(t, 0), 2) for t in q)))
        return scores


class Index:
    def __init__(self, chunks: list[Chunk], *, use_embeddings: bool | None = None,
                 use_reranker: bool | None = None, candidate_k: int | None = None,
                 rerank_k: int | None = None, reranker_model: str | None = None):
        self.chunks = chunks
        self.retrieval_backend = "rank-bm25"
        self.bm25 = None
        self._hybrid = None
        self.use_embeddings = (
            os.environ.get("WB_EVIDENCE_BI_ENCODER", "0").strip().lower() in {"1", "true", "yes", "on"}
            if use_embeddings is None else bool(use_embeddings)
        )
        self.use_reranker = (
            os.environ.get("WB_EVIDENCE_CROSS_ENCODER", "0").strip().lower() in {"1", "true", "yes", "on"}
            if use_reranker is None else bool(use_reranker)
        )
        self.candidate_k = int(candidate_k or os.environ.get("WB_EVIDENCE_CANDIDATE_K", "12"))
        self.rerank_k = int(rerank_k or os.environ.get("WB_EVIDENCE_RERANK_K", "6"))
        self.reranker_model = reranker_model or os.environ.get(
            "WB_CROSS_ENCODER_MODEL", "cross-encoder/ms-marco-MiniLM-L6-v2"
        )
        self.last_query_receipt: dict = {"schema": "evidence-intelligence.1", "status": "not_run"}
        self.last_reranker_status = "off"
        if not chunks:
            return
        corpus = [_tok(c.text) for c in chunks]
        try:
            from rank_bm25 import BM25Okapi
            self.bm25 = BM25Okapi(corpus)
        except ImportError:
            self.retrieval_backend = "lexical-fallback"
            self.bm25 = _LexicalFallback(corpus)

        if self.use_embeddings:
            try:
                from retriever import HybridIndex, Chunk as HybridChunk
                hchunks = [HybridChunk(str(c.path), c.idx, c.text) for c in chunks]
                self._hybrid = HybridIndex(hchunks, use_embeddings=True)
                self.retrieval_backend = f"bm25+bi-encoder ({self._hybrid.embed_status})"
            except Exception as exc:
                self._hybrid = None
                self.last_query_receipt = {
                    "schema": "evidence-intelligence.1",
                    "status": "degraded",
                    "bi_encoder_init_error": f"{type(exc).__name__}: {exc}",
                }

    def _cross_rerank(self, query_text: str, rows: list[EvidenceMatch]) -> tuple[list[EvidenceMatch], str | None]:
        if not self.use_reranker or not rows:
            self.last_reranker_status = "off"
            return rows, None
        try:
            from governance.evidence_intelligence import CrossEncoderReranker
            reranker = CrossEncoderReranker(self.reranker_model)
            scores = reranker.score(query_text, [r.chunk.text for r in rows])
        except Exception as exc:
            self.last_reranker_status = "unavailable"
            self.last_query_receipt.setdefault("cross_encoder_error", f"{type(exc).__name__}: {exc}")
            return rows, None
        self.last_reranker_status = "on"
        for row, score in zip(rows, scores):
            row.cross_score = float(score)
            row.reranker_model = self.reranker_model
        rows.sort(key=lambda r: (-float(r.cross_score if r.cross_score is not None else -1.0),
                                 -r.score, r.chunk.path, r.chunk.idx))
        return rows, self.reranker_model

    def query(self, control, k=TOP_K, *, min_ratio=MIN_RATIO, min_score=MIN_SCORE,
              min_bi_cosine: float | None = None) -> list[EvidenceMatch]:
        """Retrieve evidence using BM25 candidate generation plus optional bi-encoder and reranker.

        The legacy ratio/absolute BM25 gates remain intact.  Bi-encoder and cross-encoder stages
        are additive: they expand/re-rank candidates but do not turn a model score into a
        governance judgement. Numeric semantic thresholds are opt-in and must be calibrated.
        """
        self.last_query_receipt = {
            "schema": "evidence-intelligence.1",
            "bi_encoder": {"enabled": self.use_embeddings, "backend": self.retrieval_backend},
            "cross_encoder": {"enabled": self.use_reranker, "model": self.reranker_model if self.use_reranker else None},
            "candidate_k": self.candidate_k,
            "rerank_k": self.rerank_k,
            "legacy_gate": {"min_ratio": min_ratio, "min_score": min_score},
        }
        if not self.bm25 or not self.chunks:
            self.last_query_receipt["status"] = "no_documents"
            return []
        q = _tok(f"{control.title} {control.req} {control.maps}")
        query_text = f"{control.title} {control.req} {control.maps}"
        scores = self.bm25.get_scores(q)
        if not len(scores):
            self.last_query_receipt["status"] = "no_scores"
            return []
        best = float(max(scores))
        if best <= 0:
            # rank-bm25's Robertson IDF may be negative in very small corpora when
            # query terms occur in most documents.  A negative *rank* is not proof of
            # zero lexical overlap.  Re-score that edge case with the deterministic
            # positive-IDF fallback; still return no match when overlap is genuinely
            # absent.
            fallback = _LexicalFallback([_tok(c.text) for c in self.chunks])
            fallback_scores = fallback.get_scores(q)
            if not fallback_scores or max(fallback_scores) <= 0:
                self.last_query_receipt["status"] = "no_lexical_match"
                return []
            scores = fallback_scores
            best = float(max(scores))
            self.last_query_receipt["lexical_score_fallback"] = "positive-idf-small-corpus"

        candidate_n = max(int(k), self.candidate_k if self.use_embeddings or self.use_reranker else int(k))
        bm_ranked = sorted(range(len(scores)), key=lambda i: -scores[i])[:candidate_n]
        selected: dict[int, EvidenceMatch] = {}
        for i in bm_ranked:
            if scores[i] / best < min_ratio or scores[i] < min_score:
                continue
            selected[i] = EvidenceMatch(self.chunks[i], float(scores[i]), bm25_score=float(scores[i]), retrieval_methods=["bm25"])

        # Bi-encoder candidate expansion.  We intentionally do not apply a universal cosine
        # threshold here; the evaluation sweep in eval/cos_sweep.py should establish any threshold.
        if self._hybrid is not None:
            try:
                bhits = self._hybrid.search(query_text, k=candidate_n, max_per_doc=2, min_cos=0.0)
                for h in bhits:
                    i = next((j for j, c in enumerate(self.chunks)
                              if str(c.path) == str(h.chunk.doc_id) and c.idx == h.chunk.idx), None)
                    if i is None:
                        continue
                    row = selected.get(i) or EvidenceMatch(self.chunks[i], float(scores[i]), bm25_score=float(scores[i]))
                    row.bi_cosine = h.cos
                    if "bm25" not in row.retrieval_methods and h.cos is not None:
                        row.retrieval_methods.append("bi_encoder")
                    elif "bi_encoder" not in row.retrieval_methods:
                        row.retrieval_methods.append("bi_encoder")
                    selected[i] = row
            except Exception as exc:
                self.last_query_receipt["bi_encoder_error"] = f"{type(exc).__name__}: {exc}"

        rows = list(selected.values())
        if min_bi_cosine is not None:
            rows = [r for r in rows if r.bi_cosine is not None and r.bi_cosine >= float(min_bi_cosine)]
            self.last_query_receipt["min_bi_cosine"] = float(min_bi_cosine)

        rows.sort(key=lambda r: (-r.score, r.chunk.path, r.chunk.idx))
        # Keep a larger candidate pool for cross-encoder reranking; deduplication remains after
        # reranking so a better semantic match is not discarded simply because it followed a
        # lexically similar passage.
        if rows and self.use_reranker:
            rows = rows[:max(self.rerank_k, k) * 2]
            rows, model = self._cross_rerank(query_text, rows)
            self.last_query_receipt["cross_encoder"] = {
                "enabled": True, "model": model or self.reranker_model,
                "status": self.last_reranker_status,
            }
        else:
            self.last_reranker_status = "off"

        for row in rows:
            _, row.identity_tier = _path_identity(control, row.chunk.path)
        rows.sort(key=lambda row: (
            _path_identity(control, row.chunk.path)[0],
            -float(row.cross_score if row.cross_score is not None else -1.0),
            -float(row.bi_cosine if row.bi_cosine is not None else -1.0),
            -row.score,
            row.chunk.path,
            row.chunk.idx,
        ))

        out: list[EvidenceMatch] = []
        per_doc: dict[str, int] = {}
        seen: list[set[str]] = []
        for row in rows:
            if per_doc.get(row.chunk.path, 0) >= 2:
                continue
            toks = set(_tok(row.chunk.text))
            if any(len(toks & s) / max(1, len(toks | s)) > 0.6 for s in seen):
                continue
            out.append(row)
            seen.append(toks)
            per_doc[row.chunk.path] = per_doc.get(row.chunk.path, 0) + 1
            if len(out) >= int(k):
                break

        self.last_query_receipt["status"] = "ok" if out else "no_candidates_after_gates"
        self.last_query_receipt["candidate_count"] = len(selected)
        self.last_query_receipt["returned_count"] = len(out)
        self.last_query_receipt["identity_policy"] = "exact-control-first-v1"
        self.last_query_receipt["identity_tiers"] = [row.identity_tier for row in out]
        return out


def signals_for(control, signals: list[Signal]) -> list[Signal]:
    cid = control.id.split()[0].rstrip("★").strip()
    fam = cid.split(".")[0]
    return [s for s in signals if any(c == cid or c == fam or cid.startswith(c + ".") for c in s.controls)]
