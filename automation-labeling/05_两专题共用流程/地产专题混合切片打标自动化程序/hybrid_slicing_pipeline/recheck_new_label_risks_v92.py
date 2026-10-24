"""Apply the core bounded definition-risk gate to an already scanned batch.

Only NEW selections are in scope. Successful dictionary scans are reused,
original baseline labels and normal non-label fields are not re-generated.
"""
import argparse
import copy
import json
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import full_dictionary_supplement_v92 as s


def recheck(current,prior,tax,business,runner,output,only_candidates=None):
    r=copy.deepcopy(current);doc=r['document'];units=s.audit_units(r);by={u['unit_id']:u for u in units}
    index=s.index_for(tax,doc['topic']);old_pairs={(u['unit_id'],'D'+t['标签路径ID'][4:]) for u in prior['rows'] for t in u['标签明细']}
    traces={t['unit_id']:t for t in r['traces']};selected={}
    for row in r['rows']:
        uid=row['unit_id'];proofs=traces[uid].get('全字典补选证据',[])
        for tag in row['标签明细']:
            key='D'+tag['标签路径ID'][4:]
            if (uid,key) not in old_pairs:
                proof=next(p for p in proofs if p['key']==key)
                selected.setdefault(uid,[]).append(copy.deepcopy(proof))
    if only_candidates is not None:selected=copy.deepcopy(only_candidates)
    risk_count=sum(bool(s.supplement_definition_risks(d,index)) for ds in selected.values() for d in ds)
    if not risk_count:
        r['definition_risk_review_applied']={'checked_new_candidates':0,'held_new_candidates':0}
        return r
    kept,events,calls,audit,errors,remaining=s.gate_new_supplements(r,units,selected,index,runner,old_pairs)
    rows={u['unit_id']:u for u in r['rows']};before={(uid,d['key']) for uid,ds in selected.items() for d in ds}
    kept_pairs={(uid,d['key']) for uid,ds in kept.items() for d in ds};held=before-kept_pairs
    for uid,items in selected.items():
        if uid not in rows:continue
        tids={'VOC-'+d['key'][1:] for d in items};row=rows[uid];trace=traces[uid]
        row['标签明细']=[t for t in row['标签明细'] if t['标签路径ID'] not in tids]
        row['打标说明']='\n'.join(line for line in row['打标说明'].splitlines() if not any(tid in line for tid in tids))
        trace['全字典补选证据']=[p for p in trace.get('全字典补选证据',[]) if (uid,p['key']) not in before]
    for uid,items in kept.items():
        if uid in rows:
            for d in items:s.append_confirmed(rows[uid],traces[uid],d,index,doc,by[uid])
    restored,pending,cc,aa=s.restore_rows(r,units,kept,index,business,runner)
    calls+=cc;audit+=aa
    for row,trace in restored:
        rows[row['unit_id']]=row;traces[row['unit_id']]=trace
    recovered={u['unit_id'] for u,t in restored}
    r['pending_units']=[q for q in r.get('pending_units',[]) if q['unit_id'] not in recovered]+pending
    r['excluded_intervals']=[e for e in r.get('excluded_intervals',[]) if e.get('原单元ID') not in recovered and not any(e.get('原文')==by[uid]['text'] for uid in recovered)]
    for uid,row in list(rows.items()):
        local=[e for e in events if e.get('unit_id')==uid and ('待核' in e['处理'] or '未完成' in e['处理'])]
        if local:row['备注']+='；新增标签专项待核：'+'；'.join(dict.fromkeys('VOC-'+e['key'][1:]+'：'+e['原因'] for e in local))
        if not row['标签明细']:
            r['pending_units'].append({'unit_id':uid,'record_id':doc['record_id'],'来源类型':doc['kind'],
                '原文':by[uid]['text'],'起点':by[uid]['start'],'终点':by[uid]['end'],
                '原因':'新增标签专项定义未获确认，保留原范围待核，不以空标签交付',
                '旧单元':row,'补全候选':None,'校验':None,'专项标签事件':local})
            rows.pop(uid);traces.pop(uid)
    ordered=sorted(rows,key=lambda uid:by[uid]['start']);r['rows']=[rows[k] for k in ordered];r['traces']=[traces[k] for k in ordered]
    r['calls']+=calls;r['audit']+=audit;r['label_supplement_events']+=events
    resolved={(uid,'D'+t['标签路径ID'][4:]) for uid,row in rows.items() for t in row['标签明细']}
    extra=[e for e in events if '待核' in e['处理'] or '未完成' in e['处理']]
    r['label_supplement_deferred']=s.unique_deferred([e for e in r['label_supplement_deferred']+extra if (e.get('unit_id'),e.get('key')) not in resolved])
    coverage=r['label_supplement_coverage'];coverage['deferred_candidate_count']=len(r['label_supplement_deferred'])
    coverage['deferred_event_count']=coverage.get('deferred_event_count',0)+len(extra)
    coverage['remaining_facts']=list({(f['unit_id'],tuple(f['quotes']),f['fact']):f for f in coverage['remaining_facts']+remaining}.values())
    coverage['errors']=list(dict.fromkeys(coverage['errors']+errors))
    coverage['new_confirmed_tags']=sum((uid,'D'+t['标签路径ID'][4:]) not in old_pairs for uid,row in rows.items() for t in row['标签明细'])
    old_ids={u['unit_id'] for u in prior['rows']};coverage['restored_units']=sum(uid not in old_ids for uid in rows)
    all_risk_pairs={(e['unit_id'],e['key']) for e in r['label_supplement_events'] if e.get('definition_risk_review') or e['处理'].startswith('新增标签专项')}
    coverage['risk_reviewed_new_candidates']=len(all_risk_pairs);coverage['risk_held_new_candidates']=len(all_risk_pairs-resolved)
    coverage['all_candidates_adjudicated']=not coverage['errors'] and not r['label_supplement_deferred'] and not coverage['remaining_facts'] and not r['pending_units']
    r['complete']=bool(r['complete'] and coverage['all_candidates_adjudicated'])
    r['definition_risk_review_applied']={'checked_new_candidates':len(all_risk_pairs),'held_new_candidates':len(all_risk_pairs-resolved),'scope':'只核验新增高风险路径；不按关键词删除，不重新扫描193来源'}
    if doc['topic']==s.base.T2 and restored:
        from project_context_v90 import process as repair_project
        r=repair_project(r,business,runner)
    s.save_json(output/'documents'/(s.digest(doc['record_id'])+'.json'),r)
    return r


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--prior',type=Path,default=s.DEFAULT_PRIOR)
    ap.add_argument('--taxonomy',type=Path,default=s.DEFAULT_TAXONOMY);ap.add_argument('--output-dir',type=Path,required=True);a=ap.parse_args()
    current=json.loads((a.output_dir/'delivery_results.json').read_text(encoding='utf-8'))
    prior=json.loads(a.prior.read_text(encoding='utf-8'));old={r['document']['record_id']:r for r in prior['results']}
    tax=s.base.load_taxonomy(a.taxonomy);business=prior['business'];runner=s.ApiRunner(a.output_dir,10,key=os.getenv('YS_LLM_API_KEY'))
    changed={};targets=[r for r in current['results'] if not r.get('definition_risk_review_applied')]
    def work(r):
        rid=r['document']['record_id'];sig=s.digest({'input':r,'code':Path(__file__).read_text(encoding='utf-8'),'core':Path(s.__file__).read_text(encoding='utf-8')})
        cp=a.output_dir/'risk_review_checkpoints'/(s.digest(rid)+'.json')
        if cp.exists():
            cached=json.loads(cp.read_text(encoding='utf-8'))
            if cached['signature']==sig:return cached['result']
        updated=recheck(r,old[rid],tax,business,runner,a.output_dir);s.save_json(cp,{'signature':sig,'result':updated});return updated
    with ThreadPoolExecutor(max_workers=10) as pool:
        fs={pool.submit(work,r):r['document']['record_id'] for r in targets}
        for f in as_completed(fs):
            rid=fs[f];r=f.result();changed[rid]=r
            if r['definition_risk_review_applied']['checked_new_candidates']:
                print(json.dumps({'record_id':rid,**r['definition_risk_review_applied'],'errors':r['label_supplement_coverage']['errors']},ensure_ascii=False),flush=True)
    results=[changed.get(r['document']['record_id'],r) for r in current['results']]
    verification=s.validate_contract(prior,results,tax);s.save_json(a.output_dir/'supplement_contract_verification.json',verification)
    fresh=s.base.export(a.output_dir,results,current['sampling'],tax,business,runner,'api',True)
    for k in ['project_context_status','execution_manifest','new_test_status','delivery_label_reference','protocol_retry_outcomes']:
        if k in current:fresh[k]=copy.deepcopy(current[k])
    fresh['summary'].update(version=s.VERSION,new_test_scope='原80篇文章113条评论全字典扫描及新增高风险路径必要条件复核')
    fresh['delivery_changes']=[x for r in results for x in r.get('repair_changes',[])]
    fresh['supplement_status']={'sources':len(results),'fully_scanned_sources':sum(r['label_supplement_coverage']['all_branches_checked'] for r in results),
        'new_tags':sum(r['label_supplement_coverage']['new_confirmed_tags'] for r in results),
        'withdrawn_wrong_tags':sum(r['label_supplement_coverage']['withdrawn_wrong_tags'] for r in results),
        'restored_units':sum(r['label_supplement_coverage']['restored_units'] for r in results),'zero_miss_guarantee':False,
        'sources_with_deferred_candidates':sum(bool(r['label_supplement_deferred']) for r in results),'deferred_candidates':sum(len(r['label_supplement_deferred']) for r in results),
        'sources_with_remaining_facts':sum(bool(r['label_supplement_coverage']['remaining_facts']) for r in results),
        'sources_with_api_contract_errors':sum(bool(r['label_supplement_coverage']['errors']) for r in results),
        'risk_reviewed_new_candidates':sum(r['definition_risk_review_applied']['checked_new_candidates'] for r in results),
        'risk_held_new_candidates':sum(r['definition_risk_review_applied']['held_new_candidates'] for r in results)}
    s.save_json(a.output_dir/'delivery_results.json',fresh);print(json.dumps({'status':fresh['supplement_status']},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
