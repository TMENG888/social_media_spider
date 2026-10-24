"""Read-only evidence boundary audit; no reference labels or inference calls."""
import json
import sys
from pathlib import Path
import topic1_semantic_pipeline as pipeline

ROOT = Path(__file__).parent


def audit(version, batches):
    taxonomy = {t['tag_id']: t for t in json.loads((ROOT / 'inputs/taxonomy.json').read_text(encoding='utf8'))}
    for batch in batches:
        results = json.loads((ROOT / f'run_{version}/{batch}_results.json').read_text(encoding='utf8'))
        issues = []
        count = 0
        for result in results:
            for unit in result['semantic_partition']:
                for proof in unit['labels']:
                    count += 1
                    a, b = proof['proof_start'], proof['proof_end']
                    completed = pipeline.complete_evidence_span(unit['text'], a, b, taxonomy[proof['tag_id']])
                    if completed != (a, b):
                        issues.append({'source_id': result['document']['source_id'], 'unit': unit['index'],
                                       'tag_id': proof['tag_id'], 'old': proof['quote'],
                                       'completed': unit['text'][completed[0]:completed[1]]})
        print(json.dumps({'version': version, 'batch': batch, 'proof_count': count,
                          'clipped_token_proofs': len(issues), 'examples': issues[:5]}, ensure_ascii=False))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf8')
    audit(sys.argv[1], sys.argv[2:])
