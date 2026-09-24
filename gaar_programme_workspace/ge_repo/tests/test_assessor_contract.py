"""The assessor contract: the canonical element is its input, never its output.

The assessor assesses supplied evidence against an already-governed element set. It may say
whether the evidence supports an element, propose an element-level state in the engine's own
vocabulary, give its rationale, cite the passages, surface insufficiency, and raise a challenge
about the human reading. It may not author requirements.

The test that matters here is the last one: given a control whose verification guidance contains
extra test instructions, the assessor must assess the canonical elements and must not promote
those instructions into requirements. That is the boundary the whole semantic layer rests on, and
it is the exact defect the D1.3 panel showed — "Sample boundary events in the period" presented
to a reviewer as a governed gap.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import assessor as A


class _Ctl:
    def __init__(self, cid="D1.1", lib="Control Library - MGF Agentic"):
        self.id, self.lib = cid, lib
        self.title, self.req, self.owner, self.maps, self.artefacts = "t", "r", "o", "", ""


def _banner(cid="D1.1", lib="Control Library - MGF Agentic"):
    return A._provenance_banner(_Ctl(cid, lib))


# ------------------------------------------------------------------ what it may not do

def test_it_may_not_invent_requirements_from_any_of_the_four_sources():
    b = _banner()
    for source in ("the control title", "a verification procedure", "the evidence",
                   "your own interpretation"):
        assert source in b, f"the prompt does not rule out inventing a requirement from {source}"


def test_it_may_not_rewrite_the_decomposition():
    assert "do not rewrite the decomposition" in _banner()


def test_its_output_is_a_proposal_not_a_decision():
    b = _banner()
    assert "proposal" in b.lower()
    assert "not a decision" in b
    assert "not an amendment to the requirement" in b


# ------------------------------------------------------------------ what it may do

def test_paraphrase_is_permitted_but_the_proposition_is_not():
    b = _banner()
    assert "You may paraphrase an element in your rationale" in b
    assert "the proposition assessed must remain the canonical element" in b


# ------------------------------------------------------------------ the boundary test

def test_verification_guidance_is_labelled_as_not_a_requirement():
    """A ToD/ToE step reaching `gaps` is how "obtain the enforced configuration" became a finding."""
    import inspect
    src = inspect.getsource(A)
    assert "VERIFICATION GUIDANCE — NOT REQUIREMENTS" in src
    assert "NEVER copy a ToD/ToE step into `gaps`" in src
    assert "never treat a verification step as an unmet requirement" in src


def test_a_test_instruction_in_the_guidance_is_not_promoted_to_a_requirement():
    """The regression test for the architectural boundary.

    Deterministic, not a model call: the prompt must present the canonical elements as the
    obligations and the ToD/ToE material under a heading that denies it that status. A prompt
    that lists both under one heading is the defect regardless of how the model behaves on any
    given run.
    """
    import inspect
    src = inspect.getsource(A)
    req_hdr = src.index("REQUIREMENT ELEMENTS ONLY")
    ver_hdr = src.index("VERIFICATION GUIDANCE — NOT REQUIREMENTS")
    assert req_hdr < ver_hdr, "requirements must be presented before, and apart from, guidance"
    between = src[req_hdr:ver_hdr]
    assert "ToD" not in between and "ToE" not in between, \
        "verification steps appear inside the requirement block"


def test_the_guards_that_catch_it_after_the_fact_are_still_wired():
    """Belt and braces: the prompt asks, and `_validate` enforces.

    GE-110 added procedural- and restatement-gap detection because a prompt instruction is not a
    control. Both layers must remain — the prompt so the model rarely does it, the validator so
    it never reaches a reviewer when the model does.
    """
    import inspect
    src = inspect.getsource(A._validate)
    assert "procedural_gaps" in src
    assert "restate a test step" in src
    assert "gaps_are_restatements" in src
