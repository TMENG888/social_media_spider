"""Preserve actual terminal interruption without inventing a complete batch."""
import json
import argparse
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('--folder',default='test_results_v11_54_random_20261009_api')
parser.add_argument('--terminal-evidence',default='Precisely verified PID1952 stopped; session1729 actually returned exit1.')
args=parser.parse_args()
folder=Path(__file__).parent/args.folder
snapshot=json.loads((folder/'current_snapshot.json').read_text(encoding='utf-8'))
previous=json.loads((folder/'preparation.json').read_text(encoding='utf-8'))
old=json.loads(Path(previous['source_result']).read_text(encoding='utf-8'))
requested=(old.get('execution_manifest') or {}).get('requested_record_ids') or old['requested_record_ids']
actual={r['document']['record_id'] for r in snapshot['results']}
snapshot.update(terminal_status='interrupted_after_confirmed_workmanship_gate_failure',terminal_exit_code=1,
    requested_sources=len(requested),requested_record_ids=requested,
    missing_requested_sources=[k for k in requested if k not in actual],
    note=args.terminal_evidence+' Source files retained. In-flight usage may be unavailable, never counted as zero.')
(folder/'interrupted_results.json').write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'completed_sources':len(actual),'requested_sources':len(requested),
    'missing':snapshot['missing_requested_sources'],'terminal_exit_code':1},ensure_ascii=False))
