"""Production orchestration over the existing signed investigation contract."""
import json
import os
from pathlib import Path
from governance.result_contract import CanonicalSigner
from governance.investigation import InvestigationEngine, InvestigationStore, admit_segments
from governance.investigation.agents import run_to_checkpoint
from .live import LiveClient, health
from .sources import validate_source

ROLES = ('assessor', 'test_planner', 'executor', 'challenger', 'decision')
STAGES = {'examine': 'assessor', 'explain': 'assessor', 'plan': 'test_planner', 'challenge': 'challenger'}


def load(path):
    path = Path(path).resolve()
    return json.loads(path.read_text()), path.parent


def signers_for(config, root=None):
    signers = {}
    for role in ROLES:
        item = config['signers'][role]
        from .secrets import private_seed
        signer = CanonicalSigner.from_base64(item['key_id'], private_seed(item, root or Path.cwd()))
        trusted = config['trusted_keys'].get(signer.key_id, {})
        if trusted.get('public_key') != signer.public_key_b64 or role not in trusted.get('roles', []):
            raise ValueError('untrusted signing identity for ' + role)
        signers[role] = signer
    if signers['assessor'].public_key_b64 == signers['challenger'].public_key_b64:
        raise ValueError('independent challenger key required')
    return signers


def doctor(config, root):
    checks = {}
    disabled = config.get('model_stages') == 'disabled'
    for stage in STAGES:
        checks['model:' + stage] = ({'status': 'DISABLED', 'reason': 'model stages disabled by configuration'}
                                    if disabled else health(config.get('models', {}).get(stage, {})))
    try:
        signers_for(config, root)
        checks['identities'] = {'status': 'AVAILABLE'}
    except Exception as exc:
        checks['identities'] = {'status': 'UNAVAILABLE', 'reason': str(exc)}
    for sid, entry in config.get('sources', {}).items():
        try:
            if entry['source_id'] != sid:
                raise ValueError('registry source identity mismatch')
            if entry.get('evaluation_fixture') is True:
                if config.get('operation_mode') != 'evaluation' or entry.get('authority') != 'internal':
                    raise ValueError('evaluation fixture source is forbidden outside evaluation mode')
                import hashlib
                raw=(root/entry['snapshot_path']).read_bytes()
                if not raw or hashlib.sha256(raw).hexdigest()!=entry['sha256']:
                    raise ValueError('evaluation fixture source hash mismatch')
            else:
                validate_source(entry, root, config.get('trusted_keys', {}))
            checks['source:' + sid] = {'status': 'AVAILABLE'}
        except Exception as exc:
            checks['source:' + sid] = {'status': 'UNAVAILABLE', 'reason': str(exc)}
    if not config.get('sources'):
        checks['sources'] = {'status': 'UNAVAILABLE', 'reason': 'No approved source snapshots configured'}
    try:
        from governance.investigation.dependencies import load as load_knowledge
        book, digest = load_knowledge()
        checks['dependency_knowledge'] = {'status': 'AVAILABLE', 'version': book['version'], 'sha256': digest, 'edges': len(book['edges']), 'authority': 'PROPOSED_INTERNAL_KNOWLEDGE'}
    except Exception as exc:
        checks['dependency_knowledge'] = {'status': 'UNAVAILABLE', 'reason': str(exc)}
    checks['held_out_judgment'] = {'status': 'NOT_EVALUATED', 'reason': 'Independent held-out corpus and recorded inference required'}
    blockers = [k for k, v in checks.items() if v['status'] not in {'AVAILABLE', 'DISABLED'} and k != 'held_out_judgment']
    return {'status': 'BLOCKED' if blockers else 'CONFIGURED', 'checks': checks, 'blockers': blockers,
            'production_readiness': 'NOT_ESTABLISHED'}


def collect(config, root, scope):
    """Read exact operator-authorized files; never search arbitrary directories."""
    records = []
    for item in config.get('collectors', []):
        allowed = (root / item['root']).resolve(strict=True)
        path = (allowed / item['path']).resolve(strict=True)
        if not path.is_relative_to(allowed) or not path.is_file():
            raise ValueError('collector path outside approved root')
        if path.stat().st_size > 20_000_000:
            raise ValueError('evidence export exceeds collector budget')
        records.extend(admit_segments(source_bytes=path.read_bytes(), source_sha256=item['sha256'],
            source_id=item['source_id'], scope=item['scope'], expected_scope=scope,
            segments=item['segments'], authority=item['authority'], provenance=tuple(item['provenance'])))
    records.extend(collect_periodic(config, root, scope))
    if len({e.evidence_id for e in records}) != len(records):
        raise ValueError('duplicate collected evidence identity')
    return tuple(records)


def current_time(config):
    """The clock a run uses. Real time, unless a constructed demonstration signed a simulated clock."""
    from datetime import datetime
    clock = config.get("simulated_clock")
    return datetime.fromisoformat(clock) if clock else datetime.now().astimezone()


def declares_complete(package):
    if (package.get("collection") or {}).get("complete") is True:
        return True
    return any((package.get(side) or {}).get("complete") is True for side in ("primary", "independent"))


def arrival_problem(package, period_end, now, slack_minutes):
    """Collector contract, D14: an export must not claim more than time allows.

    Nothing is assessed before its period has ended. An export that declares complete collection for a
    period still in progress is not merely early: it asserts something that cannot yet be true, so it is
    an integrity event (runbook E1). A small signed slack window tolerates clock skew at the boundary.
    """
    from datetime import datetime, timedelta
    ends = datetime.fromisoformat(period_end)
    if now >= ends - timedelta(minutes=slack_minutes):
        return None
    if declares_complete(package):
        return "PREMATURE_COMPLETE"
    return "EARLY_PARTIAL"


def periodic_folder(config, root, scope):
    """The inbox folder for exactly one authorised period, or None if not configured."""
    layout = config.get('periodic_evidence')
    if not layout:
        return None
    label = layout['periods'].get(scope.period)
    if not label:
        raise ValueError('period is not covered by the standing authorisation')
    inbox = (root / layout['inbox']).resolve(strict=True)
    folder = (inbox / label).resolve()
    if not folder.is_relative_to(inbox):
        raise ValueError('period folder escaped the approved inbox')
    return folder


def collect_periodic(config, root, scope):
    """Per-period exports under a standing authorisation.

    Exact file names only, one folder per authorised period, hashed at pickup.
    The export must itself declare this system and this period, so a file placed
    in the wrong week is refused rather than silently assessed.
    """
    import hashlib, json as _json
    folder = periodic_folder(config, root, scope)
    if folder is None:
        return []
    layout, records = config['periodic_evidence'], []
    for item in layout['evidence']:
        path = (folder / item['file']).resolve(strict=True)
        if not path.is_relative_to(folder) or not path.is_file():
            raise ValueError('periodic export outside its period folder')
        if path.stat().st_size > 20_000_000:
            raise ValueError('evidence export exceeds collector budget')
        raw = path.read_bytes()
        text = raw.decode('utf-8')
        package = _json.loads(text)
        if package.get('scope') != scope.system_id or package.get('as_of') != scope.period:
            raise ValueError(f"{item['file']} declares {package.get('scope')} / {package.get('as_of')}, "
                             f"not this period ({scope.system_id} / {scope.period})")
        problem = arrival_problem(package, scope.period, current_time(config), layout.get('slack_minutes', 10))
        if problem == 'PREMATURE_COMPLETE':
            raise ValueError(f"D14: {item['file']} declares complete collection for a period ending {scope.period} "
                             "that has not ended: refused as a potential integrity event (runbook E1)")
        if problem == 'EARLY_PARTIAL':
            raise ValueError(f"{item['file']} arrived before its period ended; nothing is assessed until the period ends")
        digest = hashlib.sha256(raw).hexdigest()
        records.extend(admit_segments(source_bytes=raw, source_sha256=digest, source_id=item['evidence_id'],
            scope={'system_id': scope.system_id, 'version': scope.version, 'period': scope.period},
            expected_scope=scope,
            segments=[{'start': 0, 'end': len(text), 'evidence_id': item['evidence_id'],
                       'element_ids': item['element_ids'], 'purposes': item.get('purposes', ['operating_record']),
                       'finding_status': 'neutral'}],
            authority='internal',
            provenance=('periodic inbox', layout['authorisation_id'], 'sha256:' + digest)))
    return records


def run(config, root, investigation_id):
    report = doctor(config, root)
    if report['blockers']:
        return {'checkpoint': 'PRODUCTION_CONFIGURATION_REQUIRED', 'doctor': report}
    engine = InvestigationEngine(InvestigationStore(root / config['store'], config['trusted_keys']), config['sources'])
    rows, values = engine.snapshot(investigation_id, config.get('expected_heads', {}).get(investigation_id))
    if rows and not config.get('expected_heads', {}).get(investigation_id):
        return {'checkpoint': 'EXTERNAL_HEAD_REQUIRED', 'deployment_authorized': False}
    if 'expectations' not in values:
        return {'checkpoint': 'OWNER_AND_EXPECTATIONS_REQUIRED', 'deployment_authorized': False}
    if values['understand'].synthetic:
        raise ValueError('production entry point rejects synthetic investigations')
    signers = signers_for(config, root)
    if not config['trusted_keys'][signers['assessor'].key_id].get('require_dependency_review'):
        return {'checkpoint': 'APPROVED_DEPENDENCY_REVIEW_POLICY_REQUIRED', 'deployment_authorized': False}
    if values['understand'].control_id == 'M3.6':
        from .m36 import PROCEDURES
        policy = config['trusted_keys'][signers['test_planner'].key_id]
        required_tools = {tuple(x) for x in policy.get('required_tools_by_control', {}).get('M3.6', [])}
        if not set(PROCEDURES) <= required_tools:
            return {'checkpoint': 'APPROVED_M36_TEST_POLICY_REQUIRED', 'deployment_authorized': False}
    evidence = values['examine'].evidence if 'examine' in values else collect(config, root, values['understand'].scope)
    invokes = {stage: LiveClient(config['models'][stage], stage, signers[role], root / config['receipt_dir'], investigation_id)
               for stage, role in STAGES.items()}
    outcome = run_to_checkpoint(engine, investigation_id, signers, evidence=evidence, invokes=invokes)
    rows, values = engine.snapshot(investigation_id)
    outcome.update(investigation_id=investigation_id, head=rows[-1]['record_hash'] if rows else None,
                   production_readiness='NOT_ESTABLISHED')
    if outcome.get('checkpoint') == 'COMPLETE' and not outcome.get('gate', {}).get('assessment_finalizable'):
        outcome['checkpoint'] = 'QUALITY_GATE_BLOCKED'
    # Caller retains the head externally; never silently overwrite its trust anchor.
    return outcome
