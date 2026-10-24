"""Reuses untouched v76 delivery; only consolidation invokes real API."""
import argparse
import copy
import json
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import delivery_v76 as original
import delivery_v11 as pipeline
from semantic_merge_v77 import consolidate, VERSION, candidates, excerpt
from compare_mapreduce_v76 import compare, stats

def invariants(before, after):
    errors=[]
    if before['document']!=after['document']:errors.append('来源元数据改变')
    if before['document']['kind']=='评论' and before['rows']!=after['rows']:errors.append('评论行改变')
    old={r['unit_id']:(r,t) for r,t in zip(before['rows'],before['traces'])}
    covered=[]
    for row,trace in zip(after['rows'],after['traces']):
        ids=trace.get('合并前单元ID') or [row['unit_id']]
        covered+=ids
        expected={t['标签路径ID'] for uid in ids for t in old[uid][0]['标签明细']}
        if expected!={t['标签路径ID'] for t in row['标签明细']}:errors.append('合并标签丢失')
        if excerpt(row)!=''.join(excerpt(old[uid][0]) for uid in ids):errors.append('原文证据丢失')
        for field in ['热度指数','互动深度指数','映射文章id']:
            if any(row.get(field)!=old[uid][0].get(field) for uid in ids):errors.append('关联或指数改变')
    if len(covered)!=len(set(covered)) or set(covered)!=set(old):errors.append('原行丢失或重复')
    return errors

def main():
    p=argparse.ArgumentParser();p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,required=True);args=p.parse_args()
    original.activate()
    read=lambda path:json.loads(path.read_text(encoding='utf-8'))
    before=read(args.baseline)
    runner=pipeline.p.base.ApiRunner(args.output_dir,10,key=os.getenv('YS_LLM_API_KEY'))
    implementation=pipeline.p.base.digest(Path(__file__).with_name('semantic_merge_v77.py').read_text(encoding='utf-8'))
    def one(result):
        checkpoint=args.output_dir/'merge_documents'/(pipeline.p.base.digest({'version':VERSION,'implementation':implementation,'result':result})+'.json')
        if checkpoint.exists():return read(checkpoint)
        updated=consolidate(result,runner)
        errors=invariants(result,updated)
        if errors:
            failed=updated
            updated=copy.deepcopy(result)
            updated['calls']=failed['calls']
            updated['semantic_merge_audit']=failed.get('semantic_merge_audit',[])
            updated['semantic_merge_rollback']='；'.join(errors)
        pipeline.p.base.save_json(checkpoint,updated)
        return updated
    results=[]
    with ThreadPoolExecutor(max_workers=10) as pool:
        for f in as_completed([pool.submit(one,r) for r in before['results']]):
            results.append(f.result())
            print(json.dumps({'completed_sources':len(results),'planned':len(before['results'])}),flush=True)
    order={r['document']['record_id']:i for i,r in enumerate(before['results'])}
    results.sort(key=lambda r:order[r['document']['record_id']])
    taxonomy=pipeline.p.base.load_taxonomy(pipeline.p.v.legacy.TAXONOMY)
    data=pipeline.p.base.export(args.output_dir,results,before['sampling'],taxonomy,before['business'],runner,'api',True)
    data['summary'].update(version='delivery-v76.4-merge-v77.2-20261010',
        planned_articles=24,note='原MapReduce同批输出复用，仅新增相邻语义合并及独立验收；未重跑全量打标。')
    data['execution_manifest']=before['execution_manifest']
    reference=read(Path(__file__).with_name('independent_label_anchors_v59.json'))
    report=compare(before,data,reference)
    errors=[e for a,b in zip(before['results'],results) for e in invariants(a,b)]
    ref_old,ref_new=report['before_reference'],report['after_reference']
    nonregression=(not errors and ref_new['hit_required_tags']>=ref_old['hit_required_tags']
        and ref_new['forbidden_tag_hits']<=ref_old['forbidden_tag_hits'])
    accepted=[a for r in results for a in r.get('semantic_merge_audit',[]) if 'indices' in a and a['accepted']]
    report.update(invariant_errors=errors,accepted_merge_groups=len(accepted),
        removed_rows=sum(len(a['indices'])-1 for a in accepted),
        candidate_pairs=sum(len(candidates(r)) for r in before['results']),
        nonregression_gate_passed=nonregression,
        improvement_demonstrated=bool(nonregression and accepted),
        default_action=('保留原入口；合并版待人工语义复核' if nonregression and accepted else '未证实改善或发生退步，不启用合并；默认回到原版'),
        merge_audit=[{'record_id':r['document']['record_id'],'audit':r.get('semantic_merge_audit',[])} for r in results],
        incremental_calls=[c for c in runner.calls if not c['cache_hit']])
    # Fail closed: a global regression never replaces deliverable results.
    if not nonregression:
        data['results']=copy.deepcopy(before['results']);data['tables']=copy.deepcopy(before['tables'])
        data['summary']['merge_rollback']=True
    pipeline.p.base.save_json(args.output_dir/'delivery_results.json',data)
    pipeline.p.base.save_json(args.output_dir/'merge_comparison.json',report)
    print(json.dumps({k:report[k] for k in ['candidate_pairs','accepted_merge_groups','removed_rows','nonregression_gate_passed','default_action']},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
