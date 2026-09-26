"""Result as a Service (kit v31): GaaR sold as a Warranted Control Period, not as software or hours.

One control family, one period: every in-scope control tested on real evidence, every exception closed or formally
accepted, and a published false-assurance rate backed by a capped warranty. Four modules make the chain:

- M1 reg_to_control   a publication becomes proposed control amendments and additions, each quoting its passage;
                      a named person decides each item on its own record. Nothing is live until signed.
- M2 verifier         any agent (ours or a vendor's) answers sealed, planted cases; its false-assurance rate is
                      published with its sample size and an upper bound, or not at all.
- M3 closure          an exception is closed only by an independent retest, or held under a signed, expiring risk
                      acceptance by someone other than its owner.
- M4 warranty         a capped refund per falsely assured control, issued only when M2's measured rate qualifies.

Founding rule, inherited from the arena: a machine can propose, flag and measure; only a named person signs.
RaaS is independent assurance. It never operates the controls it assures, and control ownership stays with the bank.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import yaml

PARAMS = Path(__file__).resolve().parents[2] / "config" / "raas.yaml"


def params() -> dict:
    return yaml.safe_load(PARAMS.read_text(encoding="utf-8"))


def params_sha256() -> str:
    return hashlib.sha256(PARAMS.read_bytes()).hexdigest()


def home(path=None) -> Path:
    """Runtime state: GAAR_RAAS_HOME, or ~/gaar-raas. Never relative to the working directory (D19)."""
    p = Path(path or os.environ.get("GAAR_RAAS_HOME") or Path.home() / "gaar-raas").expanduser().resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def exists(path=None) -> bool:
    """Whether RaaS has any state here, without creating the folder: readers such as the inbox ask this first."""
    return Path(path or os.environ.get("GAAR_RAAS_HOME") or Path.home() / "gaar-raas").expanduser().is_dir()


def store(name: str, path=None):
    from governance.watcher.store import HashChainStore
    return HashChainStore(home(path) / f"{name}.jsonl", f"gaar.raas.{name}.v1")
