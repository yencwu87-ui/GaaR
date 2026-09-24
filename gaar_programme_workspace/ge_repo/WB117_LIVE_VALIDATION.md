# WB-117 live validation

```bash
export WB_COLIBRI_ENABLED=1
export WB_COLIBRI_GOVERNED_ESCALATION=1
export COLIBRI_BASE_URL=http://127.0.0.1:8000/v1
export COLIBRI_MODEL=glm-5.2-colibri
```

Routine/complex-only case should stay Ollama:
```bash
python tools/live_wb117_colibri_probe.py --role assess --control-id SAFR-2.1 --control-score 1
```

Material reasoning case should route to Colibri:
```bash
python tools/live_wb117_colibri_probe.py --role challenge --control-id SAFR-2.1 \
  --reviewer-disagreement --unresolved-strong-challenge --health
```

The probe is read-only. Verify telemetry after a real engine inference: provider/model, token
budgets, `deep_reasoning=true`, `escalation_policy=governed-v1`, and explicit reason codes.
