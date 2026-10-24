"""Re-materialize saved v5.1 responses with current deterministic checks; no API."""
import argparse
import json
from pathlib import Path
import delivery_v5 as v

class Recorded:
    def __init__(self, records):self.records=records;self.calls=[]
    def call(self, system, payload, doc, phase):
        saved=self.records[doc['record_id']]
        return saved['response'],dict(saved['metrics'],cache_hit=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('output_dir',type=Path);a=p.parse_args()
    old=json.loads((a.output_dir/'delivery_results.json').read_text(encoding='utf-8'))
    taxonomy=v.base.load_taxonomy(v.TAXONOMY)
    if v.base.digest(taxonomy)!=old['taxonomy_signature']:raise ValueError('Dictionary changed; cannot silently remap')
    records={}
    for f in (a.output_dir/'calls').glob('*.json'):
        saved=json.loads(f.read_text(encoding='utf-8'));rid=saved['metrics']['record_id']
        if rid in records:raise ValueError('Multiple generation responses for one source')
        records[rid]=saved
    runner=Recorded(records)
    results=[v.process_document(r['document'],taxonomy,old['business'],runner) for r in old['results']]
    v.reconcile_parent_relevance(results,old['business'])
    v.base.VERSION=v.VERSION
    data=v.base.export(a.output_dir,results,old['sampling'],taxonomy,old['business'],runner,'api',old['summary']['smoke_passed'])
    for k in ['pipeline','verification_mode','note','catalogue_counts']:data['summary'][k]=old['summary'][k]
    data['summary']['mapping_contract']='评论映射文章id=评论源表文章id；父文章ODS主键保留于追溯'
    data['summary']['deterministic_rematerialization']='无新增API调用，仅重放已有响应做程序核验和归属补全'
    data['taxonomy_source']=str(v.TAXONOMY)
    v.base.save_json(a.output_dir/'delivery_results.json',data)
    print(v.base.dumps(data['summary']))
