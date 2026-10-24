"""Targeted full-source boundary repair with a separate audit output."""
import json
import os
from pathlib import Path
import delivery_v8 as p


def main():
    root=Path('test_results_v8_semantic_quality_20261009_api')
    data=json.loads(Path('test_results_v8_final_20261009_api/delivery_results.json').read_text(encoding='utf-8'))
    tax=p.base.load_taxonomy(p.v.legacy.TAXONOMY)
    business=p.base.load_business()
    runner=p.base.ApiRunner(root,10,key=os.getenv('YS_LLM_API_KEY'));report=[]
    for result in data['results']:
        if result['document']['record_id'] not in {'T1-3030118674814531486','T1-879334445254348759'}:continue
        doc=result['document'];raw=result['grounding_response'];keys={a['choice_key'] for a in raw['decisions']}
        payload=p.v.legacy.request_payload(doc,tax,business)
        payload.pop('title',None);payload.pop('source_article_metadata',None);payload['parent_article_context']=''
        payload['label_catalog']=[t for t in p.v.catalogue(tax,doc['topic']) if t['choice_key'] in keys]
        payload['candidate_labels']=sorted(keys)
        fixed,calls=p.refine_semantic_quality(raw,doc,keys,payload,runner)
        item={'record_id':doc['record_id'],'before_flags':p.semantic_quality_flags(raw,doc),
            'after_flags':p.semantic_quality_flags(fixed,doc),'protocol_issues':p.check_grounded(fixed,doc,keys),
            'response':fixed,'calls':calls}
        report.append(item)
        print(p.base.dumps({k:item[k] for k in ['record_id','before_flags','after_flags','protocol_issues']}),flush=True)
        p.base.save_json(root/'semantic_quality_report.json',{'records':report})


if __name__=='__main__':main()
