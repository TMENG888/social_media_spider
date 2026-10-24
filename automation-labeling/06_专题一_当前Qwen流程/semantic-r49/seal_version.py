"""Offline acceptance seal. Does not call models or read C reference answers."""
import json, datetime, sys
from pathlib import Path
import version_contract as contract

R=Path(__file__).parent

def read(p): return json.loads(p.read_text(encoding='utf8'))

def main():
    version=sys.argv[1] if len(sys.argv)>1 else 'r22'
    dest=R/'frozen_version.json'
    if dest.exists() and read(dest)['version']==version:
        contract.verify_frozen()
        print('Existing seal verified; not overwritten')
        return
    policy=read(R/'acceptance_policy.json')
    records={}
    for b in ['A','B']:
        e=read(R/f'run_{version}'/f'evaluation_{b}.json')
        a=read(R/f'run_{version}'/f'audit_{b}.json')
        assert e['model_sources']==e['reference_sources']==10
        assert e['source_tag']['precision']>=policy['source_tag_precision_min']
        assert e['source_tag']['recall']>=policy['source_tag_recall_min']
        assert not e['structural_errors'] and not a['structural_errors']
        assert e['duplicate_slices']==e['empty_practice']==0
        assert not a['summary_numeric_review']
        records[b]={name:contract.sha(R/f'run_{version}'/name) for name in [f'{b}_results.json',f'evaluation_{b}.json',f'audit_{b}.json',f'{b}_run.json']}
    raw=Path('C:/Users/YS-Insight/Desktop/专题数据/ods_social_media_post_01.csv')
    review=R/('semantic_review_AB.md' if version=='r22' else f'semantic_review_AB_{version}.md')
    assert review.exists()
    seal={'version':version,'model':'qwen3.7-flash','frozen_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'files':contract.snapshot(),'ab_records':records,
          'semantic_review_sha256':contract.sha(review),
          'critical_errors_observed_AB':0,'raw_identity_csv_sha256':contract.sha(raw),
          'scope':'Frozen regression candidate; not a production activation',
          'c_integrity_note':('C has not informed tuning or performance assessment; analyst previously saw historical adapter comments containing C annotations.' if version=='r22' else 'C informed subsequent runtime/semantic improvements. This is a regression retest, not an independent holdout. Golden annotations were never sent to Qwen and Codex reference workbooks were not edited.'),
          'production_modified':False,'batch_300_started':False}
    dest.write_text(json.dumps(seal,ensure_ascii=False,indent=2),encoding='utf8')
    contract.verify_frozen()
    print(version+' sealed for C; A/B numerical and bounded semantic checks recorded')

if __name__=='__main__': main()
