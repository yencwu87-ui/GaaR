"""Workbench page: Results → Requirement basis (kit v22). Read-only; decisions are made one control at a time."""
from __future__ import annotations

import streamlit as st

from governance import basis


@st.cache_data(show_spinner=False)
def _report(ledger_state: tuple) -> dict:
    """Recomputed whenever a basis decision is recorded (the ledger's size and time are the cache key)."""
    return basis.report()


def _ledger_state() -> tuple:
    path = basis.ledger_path()
    return (path.stat().st_size, path.stat().st_mtime) if path.exists() else (0, 0)


def render() -> None:
    r = _report(_ledger_state())
    st.warning(f"{r['defect']}. The passages below are proposals for a person to confirm, never anchors on their own.")
    t1 = r["tier1"]
    st.markdown(f"**Pilot controls first (tier 1):** {t1['confirmed']} of {t1['controls']} confirmed"
                + (f" · open: {', '.join(t1['open'])}" if t1["open"] else ""))
    st.caption(r["meaning"])
    st.dataframe([{"Framework": fw, **{k.replace("_", " ").lower(): v for k, v in counts.items()}}
                  for fw, counts in r["summary"].items()], hide_index=True, width="stretch")
    frameworks = sorted(r["summary"])
    fw = st.selectbox("Framework", frameworks, index=frameworks.index("MAS") if "MAS" in frameworks else 0, key="basis-fw")
    rows = sorted((c for c in r["controls"] if c["framework"] == fw), key=lambda c: (c["tier"], c["control_id"]))
    for row in rows:
        label = f"{'Tier 1 · ' if row['tier'] == 1 else ''}{row['control_id']} · {row['title'][:90]} · " \
                f"{row['status'].replace('_', ' ').lower()}"
        with st.expander(label):
            st.caption(f"Requirement authority today: {row['requirement_authority']}.")
            if row["decision"]:
                d = row["decision"]
                st.success(f"{d['decision'].replace('_', ' ').title()} by {d['by']} on {d['at'][:10]}.")
            for i, cand in enumerate(row["candidates"], 1):
                st.markdown(f"**Candidate {i}** (shares {', '.join(cand['shared_terms'][:5])}) · "
                            f"`{row['instrument']}` characters {cand['start']}–{cand['end']}")
                st.caption(cand["authority"])
                st.markdown("> " + cand["quote"])
            if row["status"] == "INSTRUMENT_UNAVAILABLE":
                st.info("The instrument is not held, so no passage can be proposed. This is not a finding that no "
                        "basis exists.")
            elif not row["decision"]:
                st.code(f'python tools/gaar_basis.py confirm --framework "{fw}" --control {row["control_id"]} '
                        f'--candidate 1 --decision CONFIRMED --by "Your Name"', language="bash")
