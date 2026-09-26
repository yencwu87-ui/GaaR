#!/usr/bin/env python3
"""RaaS from the command line (block 1): the actions the inbox names, one person and one item at a time.

    python tools/gaar_raas.py propose-from-watch --item ID --file saved.pdf --by "Your Name"
    python tools/gaar_raas.py decide --proposal RCP-...                                  # lists what is undecided
    python tools/gaar_raas.py decide --proposal RCP-... --item I... --decision ACCEPT --by "Your Name" [--note ...]
    python tools/gaar_raas.py period ORD-DEMO                                            # run and seal one period
    python tools/gaar_raas.py verify --pack PACK-....json --passport PACK-....passport.json
    python tools/gaar_raas.py status

State lives in GAAR_RAAS_HOME (default ~/gaar-raas). Nothing here decides for a person: `decide` records one item, and
there is no way to accept a proposal in bulk.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def propose_from_watch(args):
    from governance.raas import watch_link
    p = watch_link.propose_from_watch(args.item, args.file, args.by)
    print(f"{p['proposal_id']}: {len(p['items'])} item(s) proposed from {p['reference']}")
    print(f"next: python tools/gaar_raas.py decide --proposal {p['proposal_id']}")


def decide(args):
    from governance.raas import reg_to_control, watch_link
    proposal, decided = reg_to_control._proposal(args.proposal)
    if not args.item:
        open_items = [i for i in proposal["items"] if i["item_id"] not in decided]
        print(f"{proposal['proposal_id']} {proposal['title']}: {len(open_items)} of {len(proposal['items'])} undecided")
        for i in open_items:
            print(f"\n{i['item_id']}  {i['action']} {i['control_id']}  {i.get('control_title', '')}")
            print(f"  \"{i['quote']}\"")
        return
    if not (args.decision and args.by):
        raise SystemExit("a decision needs --decision ACCEPT|REJECT and --by \"Your Name\"")
    record = reg_to_control.decide(args.proposal, args.item, args.decision, args.by,
                                   watch_link.publication(args.proposal), note=args.note or "")
    print(f"{record['item_id']}: {record['decision']} by {record['by']}")


def period(args):
    from governance.raas import period as runner
    out = runner.run(args.order)
    pack = out["pack"]
    print(f"{pack['order_id']} {pack['period']}: {pack['status']['headline']} ({pack['status']['tier']})")
    if pack["status"]["not_warranted_reason"]:
        print(f"  {pack['status']['not_warranted_reason']}")
    print(f"pack:     {out['pack_file']}\npassport: {out['passport_file']}")


def verify(args):
    from governance.raas import seal
    pack, passport = json.loads(Path(args.pack).read_text()), json.loads(Path(args.passport).read_text())
    register = seal.key_register()
    result = seal.verify(pack, passport, register[-1]["public_key_b64"] if register else None)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["valid"] else 1)


def status(_args):
    from governance import raas
    if not raas.exists():
        print("no RaaS state yet (GAAR_RAAS_HOME or ~/gaar-raas)")
        return
    from governance.raas import closure, store, watch_link
    periods = [r["payload"] for r in store("periods").read()]
    desk = closure.summary()
    print(f"sealed periods: {len(periods)}")
    for p in periods:
        print(f"  {p['order_id']} {p['period']}: {p['headline']}  ({p['pack_id']})")
    print(f"closure desk: {desk['total']} exception(s), {desk['still_open']} open, {desk['closed_by_retest']} closed "
          f"by retest, {desk['risk_accepted']} risk-accepted")
    print(f"proposals awaiting decisions: {len(watch_link.awaiting_decision())}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("propose-from-watch")
    p.add_argument("--item", required=True)
    p.add_argument("--file", required=True)
    p.add_argument("--by", required=True)
    p.set_defaults(func=propose_from_watch)
    d = sub.add_parser("decide")
    d.add_argument("--proposal", required=True)
    d.add_argument("--item")
    d.add_argument("--decision", choices=["ACCEPT", "REJECT"])
    d.add_argument("--by")
    d.add_argument("--note")
    d.set_defaults(func=decide)
    r = sub.add_parser("period")
    r.add_argument("order")
    r.set_defaults(func=period)
    v = sub.add_parser("verify")
    v.add_argument("--pack", required=True)
    v.add_argument("--passport", required=True)
    v.set_defaults(func=verify)
    s = sub.add_parser("status")
    s.set_defaults(func=status)
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except ValueError as refusal:
        raise SystemExit(f"refused: {refusal}")


if __name__ == "__main__":
    main()
