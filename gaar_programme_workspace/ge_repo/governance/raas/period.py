"""One order's period, end to end (block 1, B1-1 and B1-5): the whole chain runs as one command and ends in a sealed pack.

    python -m governance.raas.period ORD-DEMO            # an order in the RaaS home, or config/raas_orders/
    python -m governance.raas.period path/to/order.yaml

1. M1: every proposal made from the watch is in the pack; one with undecided items leaves the period incomplete.
2. Series -> M3: the series' findings for the period are on the closure desk (idempotent); the pack counts the
   exceptions on the order's controls only.
3. M2 with planted cases (B1-5): the order's agent answers `verification.planted_per_period` planted cases (500, which
   tolerates exactly one miss) mixed with as many clean ones. The draw's seed is derived from the tenant's secret
   signing key, so neither the agent nor a control owner can know the cases in advance; each period draws new ones.
   The pack carries a commitment to the seed, and the tenant's verification ledger keeps the seed for an auditor.
4. M4: a warranty only when the 95% upper bound qualifies (warranty.tier) and the period is complete: a warranty over
   exceptions still open would insure known failures.
5. The pack is sealed with its passport (seal.py) and written to the RaaS home. A period is sealed once.
"""
from __future__ import annotations

import hashlib
import hmac
import importlib
import json
import sys
from datetime import date
from pathlib import Path

import yaml

from . import closure, home, params, reg_to_control, series as feed, store, verifier, warranty
from .result import result_pack
from .seal import seal, signer
from .watch_link import links

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "config" / "raas_orders"
REQUIRED = ("order_id", "customer", "control_family", "period", "period_end", "controls", "agent", "issued_by")


def load_order(ref, path=None) -> dict:
    candidates = [Path(str(ref)).expanduser(), home(path) / "orders" / f"{ref}.yaml", EXAMPLES / f"{ref}.yaml"]
    found = next((c for c in candidates if c.is_file()), None)
    if found is None:
        raise ValueError(f"no order {ref}: put it in {home(path) / 'orders'}/{ref}.yaml")
    order = yaml.safe_load(found.read_text(encoding="utf-8")) or {}
    missing = [k for k in REQUIRED if not order.get(k)]
    if missing:
        raise ValueError(f"order {found.name} is missing {', '.join(missing)}")
    date.fromisoformat(str(order["period_end"]))
    return {**order, "period_end": str(order["period_end"]), "file": str(found)}


def agent_for(dotted: str):
    """Only GaaR's own modules name an agent here; a vendor's agent arrives through the adapter (block 3)."""
    module, _, name = dotted.partition(":")
    if not module.startswith("governance.") or not name:
        raise ValueError(f"agent {dotted!r} must be module:function inside governance/")
    return getattr(importlib.import_module(module), name)


def sealed_seed(order_id: str, period: str, path=None) -> int:
    key_file = home(path) / "keys" / "pack-signing.key"
    signer(path)                                                    # creates the tenant key on first use
    mac = hmac.new(key_file.read_bytes(), f"planted|{order_id}|{period}".encode(), hashlib.sha256).digest()
    return int.from_bytes(mac[:4], "big")


def _control_sets(path=None) -> list[dict]:
    out = []
    for link in links(path).values():
        try:
            out.append(reg_to_control.control_set(link["proposal_id"], path=path))
        except ValueError:
            proposal, _ = reg_to_control._proposal(link["proposal_id"], path)
            out.append({"proposal_id": proposal["proposal_id"], "reference": proposal["reference"], "status": "UNSIGNED",
                        "accepted": [], "rejected": 0, "signed_by": []})
    return out


def sealed(order_id: str, period: str, path=None) -> dict | None:
    return next((r["payload"] for r in store("periods", path).read()
                 if r["payload"]["order_id"] == order_id and r["payload"]["period"] == period), None)


def run(ref, path=None) -> dict:
    order = load_order(ref, path)
    oid, period = order["order_id"], str(order["period"])
    done = sealed(oid, period, path)
    if done:
        raise ValueError(f"{oid} {period} is already sealed as {done['pack_id']}: a period is sealed once")
    controls = [str(c) for c in order["controls"]]
    fed = feed.open_from_series(order["series"], path) if order.get("series") else []
    sets = _control_sets(path)
    p = params()["verification"]
    n_cases = round(p["planted_per_period"] / p["planted_share"])
    seed = sealed_seed(oid, period, path)
    v = verifier.verify(agent_for(order["agent"]), order["agent"], n_cases, seed, sponsor=order["customer"], path=path)
    desk = closure.summary(as_of=order["period_end"], path=path, controls=controls)
    band = warranty.tier(v)
    certificate, reason = None, band["reason"] + f": {band['tier']}, no warranty"
    unsigned = [s["reference"] for s in sets if s["status"] != "SIGNED"]
    if band["tier"] == "WARRANTED" and (desk["still_open"] or unsigned):
        # A warranty over known open failures would insure them: none until the period is complete.
        reason = (f"{desk['still_open']} exception(s) still open" if desk["still_open"] else
                  f"{len(unsigned)} regulatory change(s) not yet signed") + ": no warranty until the period is complete"
    elif band["tier"] == "WARRANTED":
        fee = warranty.price(controls=len(controls), exceptions_closed=desk["billable"],
                             reg_changes=sum(s["status"] == "SIGNED" for s in sets))["total"]
        certificate = warranty.issue(oid, controls, v, fee, order["issued_by"], order["period_end"], path=path)
        reason = ""
    pack = result_pack(oid, order["control_family"], period, controls, sets, v, desk, certificate, reason)
    pack["lineage"] = {"order_file_sha256": hashlib.sha256(Path(order["file"]).read_bytes()).hexdigest(),
                       "series": order.get("series"), "series_periods_fed": [f["period"] for f in fed],
                       "exceptions": [r["exception_id"] for r in desk["exceptions"]],
                       "proposals": [s["proposal_id"] for s in sets], "verification_id": v["verification_id"],
                       "planted_seed_commitment": hashlib.sha256(str(seed).encode()).hexdigest()}
    passport = seal(pack, path)
    folder = home(path) / "packs"
    folder.mkdir(parents=True, exist_ok=True)
    pack_file, passport_file = folder / f"{pack['pack_id']}.json", folder / f"{pack['pack_id']}.passport.json"
    pack_file.write_text(json.dumps(pack, indent=1, default=str) + "\n")
    passport_file.write_text(json.dumps(passport, indent=1) + "\n")
    store("periods", path).append("RaaSPeriodSealed", {
        "order_id": oid, "period": period, "pack_id": pack["pack_id"], "headline": pack["status"]["headline"],
        "content_hash": passport["content_hash"], "passport_digest": passport["passport_digest"],
        "pack_file": pack_file.name, "at": passport["sealed_at"]})
    return {"pack": pack, "passport": passport, "pack_file": str(pack_file), "passport_file": str(passport_file)}


def due_orders(config_path, today: str, path=None) -> list[str]:
    """Orders in the RaaS home over this series whose period has ended and is not sealed yet."""
    folder = home(path) / "orders"
    out = []
    for f in sorted(folder.glob("*.yaml")) if folder.is_dir() else []:
        order = load_order(f, path)
        if not order.get("series") or Path(order["series"]).expanduser().resolve() != Path(config_path).resolve():
            continue
        if order["period_end"] <= today and not sealed(order["order_id"], str(order["period"]), path):
            out.append(str(f))
    return out


def main(argv=None):
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        raise SystemExit("usage: python -m governance.raas.period ORDER_ID_OR_FILE")
    out = run(args[0])
    pack = out["pack"]
    print(f"{pack['order_id']} {pack['period']}: {pack['status']['headline']} ({pack['status']['tier']})")
    print(f"pack:     {out['pack_file']}")
    print(f"passport: {out['passport_file']}")


if __name__ == "__main__":
    main()
