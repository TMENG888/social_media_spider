"""Freeze checks do not contain annotation answers and are safe for runner use."""
import json,hashlib
from pathlib import Path
R=Path(__file__).parent
CODE=['topic1_semantic_pipeline.py','exhaustive_labels.py','label_candidates.py','topic1_identity.py','summary_evidence.py','run_regression.py','run_batch300.py','version_contract.py']
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def snapshot():
 paths=[R/p for p in CODE]+list((R/'production_snapshot').glob('*.py'))+list((R/'inputs').glob('*.json'))+[R/'acceptance_policy.json']
 return {str(p.relative_to(R)).replace('\\','/'):sha(p) for p in paths}
def verify_frozen():
 f=json.loads((R/'frozen_version.json').read_text(encoding='utf8'))
 if snapshot()!=f['files']:raise RuntimeError('Implementation or frozen inputs changed; cannot use C as frozen-version acceptance')
 return f
