# Synthetic M3.6 experiment pack

This pack reuses the four frozen M3.6 experimental cases already present in the workbench:

1. Retail credit decisioning validation
2. Contact-centre generative assistant pilot
3. AML transaction-monitoring prioritisation change
4. High-impact customer eligibility assessment

The lifecycle/revalidation standard was added because revalidation triggers are normally held
outside an individual validation report. Every file is marked `SYNTHETIC_DEMO_ONLY`.

Use this pack to test acquisition, exact-control retrieval, admission, assessment, independent
challenge, Quality Gate, signing and replay. Do not present it as MAS source material, real
institutional evidence, production compliance proof, or human ground truth.

From `ge_repo`, prepare the governed dossier with:

```bash
python tools/synthetic_m36_demo.py
```

