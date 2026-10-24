"""Real-API, cached regression of deferred positive evidence; no source writes."""
import argparse
import copy
import json
import os
from pathlib import Path
import delivery_v8 as p


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    original=json.loads(args.input.read_text(encoding='utf-8'))
    taxonomy=p.base.load_taxonomy(p.v.legacy.TAXONOMY)
    runner=p.base.ApiRunner(args.output,10,key=os.getenv('YS_LLM_API_KEY'))
    report=[]
    targets={'T1-8000912876517502279','T1-3030118674814531486','T2-75368'}
    for previous in original['results']:
        doc=previous['document']
        if doc['record_id'] not in targets:continue
        raw=copy.deepcopy(previous['grounding_response'])
        index=p.v.registry(taxonomy,doc['topic'])
        keys={a['choice_key'] for a in raw['decisions']}
        deferred={a['choice_key'] for a in raw['decisions'] if a.get('status')=='ambiguous'
            and any(s in a.get('why','') for s in ['逐字定位','单元索引','直接证据区间','对象引文','模型引文'])}
        payload={'label_catalog':[t for t in p.v.catalogue(taxonomy,doc['topic']) if t['choice_key'] in keys]}
        repaired,calls=p.repair_decision_partition(raw,doc,keys,index,payload,runner,deferred)
        repaired=p.reanchor_literal_evidence(repaired,doc)
        repaired,unlocated=p.defer_unlocated_labels(repaired,doc,keys)
        issues=p.check_grounded(repaired,doc,keys)
        recovered=[a for a in repaired['decisions'] if a['choice_key'] in deferred and a['status']=='supported']
        item={'record_id':doc['record_id'],'targeted_keys':sorted(deferred),'recovered':recovered,
            'remaining':[a for a in repaired['decisions'] if a['choice_key'] in deferred and a['status']!='supported'],
            'protocol_issues':issues,'response':repaired,'calls':calls,'unlocated':unlocated}
        report.append(item)
        print(p.base.dumps({k:item[k] for k in ['record_id','targeted_keys','recovered','remaining','protocol_issues']}),flush=True)
    p.base.save_json(args.output/'targeted_recovery_report.json',{'records':report})


if __name__=='__main__':main()
