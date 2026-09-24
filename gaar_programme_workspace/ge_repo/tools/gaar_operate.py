#!/usr/bin/env python3
"""One production entry point. No fixture fallback or manufactured authorization."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from governance.operations.runtime import load, doctor, run
from governance.operations.sources import snapshot

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--investigation-id')
    parser.add_argument('action', choices=['doctor', 'run', 'fetch-sources', 'benchmark', 'evaluate-stages'])
    args = parser.parse_args()
    try:
        config, root = load(args.config)
        if args.action == 'doctor': result = doctor(config, root)
        elif args.action == 'evaluate-stages':
            from governance.operations.stage_evaluation import evaluate
            result = evaluate(config, root)
        elif args.action == 'benchmark':
            from governance.operations.benchmark import evaluate
            result = evaluate(config, root)
        elif args.action == 'fetch-sources':
            result = {'snapshots': [snapshot(s, root / 'source_quarantine') for s in config.get('source_candidates', [])]}
        else:
            if not args.investigation_id: parser.error('run requires --investigation-id')
            result = run(config, root, args.investigation_id)
        print(json.dumps(result, indent=2))
        return 2 if result.get('status') in {'BLOCKED', 'NOT_EVALUATED', 'PARTIAL'} or result.get('gate', {}).get('assessment_finalizable') is False or result.get('checkpoint') not in (None, 'COMPLETE') else 0
    except Exception as exc:
        print(json.dumps({'checkpoint': 'UNAVAILABLE', 'error': f'{type(exc).__name__}: {exc}', 'deployment_authorized': False}, indent=2))
        return 2
if __name__ == '__main__': sys.exit(main())
