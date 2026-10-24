"""One bounded retry of API/contract failures, never semantic opinion voting."""
import argparse
import copy
import json
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import full_dictionary_supplement_v92 as s


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--prior',type=Path,default=s.DEFAULT_PRIOR)
    ap.add_argument('--taxonomy',type=Path,default=s.DEFAULT_TAXONOMY);ap.add_argument('--output-dir',type=Path,required=True)
    ap.add_argument('--record-id',help='Explicit source with a remaining structural error, never semantic disagreement')
    ap.add_argument('--branch-cap',type=int,default=48);a=ap.parse_args()
    if a.record_id and a.branch_cap>=48:ap.error('Targeted second contract recovery requires smaller branches')
    current=json.loads((a.output_dir/'delivery_results.json').read_text(encoding='utf-8'))
    prior=json.loads(a.prior.read_text(encoding='utf-8'));baseline={r['document']['record_id']:r for r in prior['results']}
    tax=s.base.load_taxonomy(a.taxonomy);business=prior['business'];runner=s.ApiRunner(a.output_dir,10,key=os.getenv('YS_LLM_API_KEY'))
    failed=[r for r in current['results'] if r['label_supplement_coverage']['errors'] and
        (r['document']['record_id']==a.record_id and not r.get('protocol_small_branch_recovery') if a.record_id else not r.get('protocol_retry_attempt'))]
    if not failed:print(json.dumps({'protocol_retry_sources':0}));return
    old={r['document']['record_id']:r for r in failed};updated={};outcomes=[]
    with ThreadPoolExecutor(max_workers=10) as pool:
        fs={pool.submit(s.process,baseline[r['document']['record_id']],tax,business,runner,a.output_dir,a.branch_cap):r['document']['record_id'] for r in failed}
        for f in as_completed(fs):
            rid=fs[f];new=f.result();previous=old[rid]
            s.save_json(a.output_dir/'protocol_retry_history'/(s.digest(rid)+('-cap'+str(a.branch_cap) if a.record_id else '')+'.json'),previous)
            new['protocol_retry_attempt']={'old_errors':previous['label_supplement_coverage']['errors'],
                'new_errors':new['label_supplement_coverage']['errors'],'scope':'只重试实际API或结构错误，不因语义不确定重复投票'}
            if a.record_id:new['protocol_small_branch_recovery']={'branch_cap':a.branch_cap,'previous_attempt':previous.get('protocol_retry_attempt'),'scope':'已有裁决数组越界，收窄结构枚举并缩小分组的一次恢复'}
            new['calls']=list({c['request_key']:c for c in previous['calls']+new['calls']}.values())
            updated[rid]=new;outcomes.append({'record_id':rid,**new['protocol_retry_attempt']})
            print(json.dumps(outcomes[-1],ensure_ascii=False),flush=True)
    results=[updated.get(r['document']['record_id'],r) for r in current['results']]
    verification=s.validate_contract(prior,results,tax);s.save_json(a.output_dir/'supplement_contract_verification.json',verification)
    fresh=s.base.export(a.output_dir,results,current['sampling'],tax,business,runner,'api',True)
    for k in ['project_context_status','execution_manifest','new_test_status','delivery_label_reference']:
        if k in current:fresh[k]=copy.deepcopy(current[k])
    fresh['summary'].update(version=s.VERSION,new_test_scope='原80篇文章和113条评论全字典分组复测；只对实际API/合同错误做一次定向恢复')
    fresh['delivery_changes']=[x for r in results for x in r.get('repair_changes',[])]
    fresh['supplement_status']={'sources':len(results),'fully_scanned_sources':sum(r['label_supplement_coverage']['all_branches_checked'] for r in results),
        'new_tags':sum(r['label_supplement_coverage']['new_confirmed_tags'] for r in results),
        'withdrawn_wrong_tags':sum(r['label_supplement_coverage']['withdrawn_wrong_tags'] for r in results),
        'restored_units':sum(r['label_supplement_coverage']['restored_units'] for r in results),'zero_miss_guarantee':False,
        'sources_with_deferred_candidates':sum(bool(r['label_supplement_deferred']) for r in results),
        'deferred_candidates':sum(len(r['label_supplement_deferred']) for r in results),
        'sources_with_remaining_facts':sum(bool(r['label_supplement_coverage']['remaining_facts']) for r in results),
        'sources_with_api_contract_errors':sum(bool(r['label_supplement_coverage']['errors']) for r in results)}
    fresh['protocol_retry_outcomes']=current.get('protocol_retry_outcomes',[])+outcomes
    s.save_json(a.output_dir/'delivery_results.json',fresh)
    print(json.dumps({'status':fresh['supplement_status']},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
