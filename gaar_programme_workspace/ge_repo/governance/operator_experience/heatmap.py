"""WB-130: reproducible attention heatmap, not an invented numerical risk score."""
from __future__ import annotations
from collections import defaultdict

THEMES = {
    'AI model governance': ('model', 'algorithm', 'ai ', 'llm', 'bias', 'fairness'),
    'Identity & access': ('access', 'identity', 'privilege', 'authentication', 'authorisation', 'authorization'),
    'Security & vulnerability': ('security', 'vulnerab', 'patch', 'malware', 'cyber'),
    'Data & privacy': ('privacy', 'personal data', 'data protection', 'retention'),
    'Change & deployment': ('change', 'deploy', 'release', 'configuration'),
    'Third-party & supply chain': ('third party', 'third-party', 'vendor', 'supplier', 'outsourc'),
    'Governance & oversight': ('governance', 'board', 'accountability', 'oversight', 'approval'),
    'Resilience & incidents': ('incident', 'continuity', 'resilien', 'recovery', 'outage'),
}

def theme_for(title: str) -> str:
    name = str(title or '').lower()
    return next((theme for theme, words in THEMES.items() if any(w in name for w in words)), 'Other / unmapped')


def classify(row: dict, living: dict | None = None) -> str:
    """Attention classes, not risk likelihood/impact or legal materiality."""
    living = living or {}
    if living.get('quality_gate') == 'BLOCKED' or (row.get('challenge') or {}).get('unresolved_strong'):
        return 'Exception / blocked'
    if living.get('current_state') in ('REVIEW_REQUIRED', 'REASSESSING'):
        return 'Reassessment due'
    if not row.get('has_evidence'):
        return 'Evidence missing'
    if row.get('next_action', {}).get('kind') in ('gate', 'decision', 'review'):
        return 'Human attention'
    if living.get('current_state') == 'CURRENT' and living.get('quality_gate') == 'FINALIZABLE':
        return 'Current / gate passed'
    return 'Not yet verified'


def portfolio_snapshot(queue: list[dict], living: list[dict], jobs: list | None = None,
                       watcher_health: list[dict] | None = None) -> dict:
    indexed = {(str(x.get('framework')), str(x.get('control_id'))):x for x in living}
    by_theme = defaultdict(lambda: defaultdict(int))
    by_framework = defaultdict(lambda: defaultdict(int))
    hotspots=[]
    documented=defaultdict(lambda: defaultdict(int))
    for row in queue:
        v=indexed.get((str(row.get('library')), str(row.get('control_id'))), {})
        category=classify(row,v)
        theme=theme_for(row.get('title'))
        by_theme[theme][category]+=1
        by_framework[str(row.get('library') or 'Unknown')][category]+=1
        if v.get('current_result') and v.get('current_state') in ('CURRENT','REVIEW_REQUIRED','REASSESSING'):
            decision=str(v.get('decision') or '')
            if decision in ('FAIL','CONDITIONAL_PASS','PASS'):
                documented[theme][decision]+=1
        if category != 'Current / gate passed':
            hotspots.append({'Framework':row.get('library'),'Control':row.get('control_id'),
                             'Theme':theme,'Attention':category,
                             'Reason':row.get('next_action',{}).get('label') or category,
                             'Cycle':row.get('cycle_id') or '—'})
    order=['Exception / blocked','Reassessment due','Evidence missing','Human attention','Not yet verified','Current / gate passed']
    hotspots.sort(key=lambda r:(order.index(r['Attention']),str(r['Framework']),str(r['Control'])))
    jobs=jobs or []
    health=watcher_health or []
    return {'total':len(queue),'living_results':len(living), 'hotspots':hotspots,
            'by_theme':{k:dict(v) for k,v in sorted(by_theme.items())},
            'documented_findings':{k:dict(v) for k,v in sorted(documented.items())},
            'by_framework':{k:dict(v) for k,v in sorted(by_framework.items())},
            'statuses':{s:sum(x.get(s,0) for x in by_theme.values()) for s in order},
            'jobs':len(jobs),'watcher_healthy':sum(h.get('status') == 'OK' for h in health),
            'watcher_degraded':sum(h.get('status') in ('DEGRADED','BLOCKED','INVALID_DOCUMENT','STALE') for h in health)}
