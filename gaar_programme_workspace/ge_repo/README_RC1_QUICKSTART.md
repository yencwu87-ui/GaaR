# GaaR RC1 Quickstart

## 1. Install
```bash
python3 -m pip install -r requirements.txt
```

## 2. Core flags
```bash
export WB_GAAR_RESULT_ENABLE=1
export WB_GAAR_AI_AUDITOR=1
export WB_GAAR_CHANGE_INTELLIGENCE=1
export WB_GAAR_REASSESSMENT_WORKFLOW=1
export WB_GAAR_QUALITY_GATE=1
export WB_GAAR_AUTOPILOT=1
export WB_COLIBRI_GOVERNED_ESCALATION=1
```

## 3. Readiness
```bash
python -m compileall -q .
python tools/release_probe.py
```

## 4. Offline deterministic story
```bash
python tools/demo_offline_story.py
```

## 5. UI
```bash
./start_ui.sh
```

## 6. RaaS API
```bash
python tools/raas_serve.py --host 127.0.0.1 --port 8787
curl http://127.0.0.1:8787/health
curl http://127.0.0.1:8787/v1/living
```

If binding outside localhost, set `WB_GAAR_API_KEY` and put the service behind TLS / enterprise auth.

## 7. Watcher
Edit `config/watcher_sources.yaml`, explicitly approve source authority, then enable the selected source. Test once:
```bash
python tools/watcher_probe.py --run
```

## 8. Evidence Scout
```bash
python tools/evidence_scout_probe.py \
  --root /path/to/approved/evidence \
  --control M3.6 --framework MAS \
  --requirement "your governed requirement text"
```
