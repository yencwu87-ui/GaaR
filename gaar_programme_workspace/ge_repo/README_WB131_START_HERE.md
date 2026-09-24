# GaaR WB-131 — Watcher Git workspace

**For normal use:** open Streamlit → **Watcher** → **Regulatory Git workspace**.

1. A discovered document is a *candidate*, not a new law applicable to you.
2. **ADD** a precise version to your assessment staging area.
3. **DIFF** the version and verify official origin, type, status and relevance.
4. **COMMIT** with your reviewer name and rationale; the workspace Ed25519 key signs it.
5. **PUSH**. Law/rule or reviewed guidance can request *impact review* and enqueue
   an Autopilot job; consultations, standards, research and threats create
   non-binding planning/reference/exposure links instead.

The original review cycle, human decision and Quality Gate remain unchanged.
This is a Git-like *governance workflow*, not a GitHub remote push or a regulator API.

## Quick, safe smoke test (no production ledgers used)

```bash
cd "$HOME/gaar_wb131_workspace/ge_repo"
source .venv/bin/activate
python tools/watcher_git_demo.py
```

It uses a fictional regulator.example.test and an ephemeral signing key, all inside
a temporary directory. It NEVER claims it downloaded from MAS, FCA or PRA.

For normal UI with your own signing identity:

```bash
source "$HOME/.config/gaar/result-signing.env"
./start_ui.sh --server.address 127.0.0.1 --server.port 8503
```

See `WB131_WATCHER_GIT_WORKFLOW.md` for exact CLI flags, Mac setup, immutable
version behavior, source cataloguing and limitations.
