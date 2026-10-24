"""Recover only supported candidates blocked by misclassified risk metadata.

General definition risks are not past semantic rejections. Genuine unsupported
verdicts and real historic conflicts never enter this one bounded recovery.
"""
import argparse,copy,json,os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import full_dictionary_supplement_v92 as s
from recheck_new_label_risks_v92 import recheck


def targets(r):
    if r.get('risk_contract_recovered'):return {}
    by={}
    for e in r['label_supplement_events']:
        if e['处理']!='新增标签专项争议转待核' or e.get('verdict')!='supported':continue
        if '历史拒绝必要条件未有据解释，不自动加回' not in e.get('program_issues',[]):continue
        if s.historic_rejections(r,e['unit_id'],e['key']):continue
        c=copy.deepcopy(e);c.pop('history_conflicts',None)
        by.setdefault(e['unit_id'],[]).append(c)
    return by


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--prior',type=Path,default=s.DEFAULT_PRIOR)
    ap.add_argument('--taxonomy',type=Path,default=s.DEFAULT_TAXONOMY);ap.add_argument('--output-dir',type=Path,required=True);a=ap.parse_args()
    current=json.loads((a.output_dir/'delivery_results.json').read_text(encoding='utf-8'))
    prior=json.loads(a.prior.read_text(encoding='utf-8'));old={r['document']['record_id']:r for r in prior['results']}
    tax=s.base.load_taxonomy(a.taxonomy);runner=s.ApiRunner(a.output_dir,10,key=os.getenv('YS_LLM_API_KEY'));business=prior['business']
    selected=[(r,targets(r)) for r in current['results']];selected=[(r,cs) for r,cs in selected if cs]
    print(json.dumps({'target_sources':len(selected),'supported_contract_candidates':sum(len(ds) for r,cs in selected for ds in cs.values())}),flush=True)
    s.save_json(a.output_dir/'risk_review_protocol_history'/'before_contract_recovery.json',current)
    changed={}
    def work(r,cs):
        rid=r['document']['record_id'];cp=a.output_dir/'risk_contract_checkpoints'/(s.digest(rid)+'.json')
        if cp.exists():return json.loads(cp.read_text(encoding='utf-8'))
        new=recheck(r,old[rid],tax,business,runner,a.output_dir,cs)
        new['risk_contract_recovered']={'candidate_count':sum(map(len,cs.values())),'scope':'只修一般风险被误作历史否决的合同错误；不复投真实unsupported'}
        s.save_json(cp,new);return new
    with ThreadPoolExecutor(max_workers=10) as pool:
        fs={pool.submit(work,r,cs):r['document']['record_id'] for r,cs in selected}
        for f in as_completed(fs):
            rid=fs[f];changed[rid]=f.result();r=changed[rid]
            print(json.dumps({'record_id':rid,'new_tags':r['label_supplement_coverage']['new_confirmed_tags'],'errors':r['label_supplement_coverage']['errors']},ensure_ascii=False),flush=True)
    results=[changed.get(r['document']['record_id'],r) for r in current['results']]
    verification=s.validate_contract(prior,results,tax);s.save_json(a.output_dir/'supplement_contract_verification.json',verification)
    fresh=s.base.export(a.output_dir,results,current['sampling'],tax,business,runner,'api',True)
    for k in ['project_context_status','execution_manifest','new_test_status','delivery_label_reference','protocol_retry_outcomes']:
        if k in current:fresh[k]=copy.deepcopy(current[k])
    fresh['summary'].update(version=s.VERSION,new_test_scope='原80篇文章113条评论全字典扫描、风险路径核验及有据合同恢复')
    fresh['delivery_changes']=[x for r in results for x in r.get('repair_changes',[])]
    status=copy.deepcopy(current['supplement_status'])
    for name,field in [('fully_scanned_sources','all_branches_checked'),('new_tags','new_confirmed_tags'),('withdrawn_wrong_tags','withdrawn_wrong_tags'),('restored_units','restored_units')]:
        status[name]=sum(r['label_supplement_coverage'][field] for r in results)
    status.update(deferred_candidates=sum(len(r['label_supplement_deferred']) for r in results),
        sources_with_deferred_candidates=sum(bool(r['label_supplement_deferred']) for r in results),
        sources_with_remaining_facts=sum(bool(r['label_supplement_coverage']['remaining_facts']) for r in results),
        sources_with_api_contract_errors=sum(bool(r['label_supplement_coverage']['errors']) for r in results),
        risk_reviewed_new_candidates=sum(r['definition_risk_review_applied']['checked_new_candidates'] for r in results),
        risk_held_new_candidates=sum(r['definition_risk_review_applied']['held_new_candidates'] for r in results))
    fresh['supplement_status']=status;s.save_json(a.output_dir/'delivery_results.json',fresh)
    print(json.dumps({'status':status},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
