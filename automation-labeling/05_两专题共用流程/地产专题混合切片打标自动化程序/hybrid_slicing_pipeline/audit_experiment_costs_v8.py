"""Deduplicate preserved call files, including failed trials and copied caches.

This is an evidence ledger, not the gateway invoice. Historical overwritten
attempts cannot be reconstructed and are not asserted to cost zero.
"""
import hashlib
import json
from pathlib import Path
import delivery_v8 as p


def main():
    folders=sorted([Path('test_results_v7_20261009_api')]+list(Path('.').glob('test_results_v8*')))
    unique={};file_count=0
    for folder in folders:
        for file in sorted((folder/'calls').glob('*.json')):
            saved=json.loads(file.read_text(encoding='utf-8'));metrics=saved.get('metrics')
            if not isinstance(metrics,dict):continue
            file_count+=1
            # Copies retain content exactly. Include seconds/attempts/response
            # so fresh calls with the same prompt are not merged as cache hits.
            identity=hashlib.sha256(p.base.dumps(saved).encode('utf-8')).hexdigest()
            entry=unique.setdefault(identity,{'metrics':metrics,'files':[]})
            entry['files'].append(str(file))
    entries=list(unique.values())
    known=sum(x['metrics'].get('estimated_yuan') or 0 for x in entries)
    unknown=sum(x['metrics'].get('estimated_yuan') is None or bool(x['metrics'].get('unknown_attempt_usage')) for x in entries)
    report={'scope':[str(f) for f in folders],'preserved_files':file_count,'distinct_preserved_calls':len(entries),
        'duplicate_cache_copies':file_count-len(entries),'known_estimated_yuan':known,
        'calls_with_unknown_price_or_usage':unknown,'entries':entries,
        'limitations':'仅统计仍保存的调用文件；不代表账单，不保证涵盖被覆盖的历史尝试。未知价格/usage不按零计费。包含失败试验，不与关联交付费用混称。'}
    p.base.save_json(Path('test_results_v8_integrated_20261009_api')/'experiment_cost_ledger.json',report)
    print(p.base.dumps({k:v for k,v in report.items() if k!='entries'}))


if __name__=='__main__':main()
