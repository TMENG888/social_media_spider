"""Resume only sources with exhausted transient requests; reuse success cache."""
import argparse,json,os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import completeness_v89 as v
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--output-dir',type=Path,required=True);a=ap.parse_args()
 fn=a.output_dir/'delivery_results.json';p=json.loads(fn.read_text(encoding='utf-8'));old=json.loads(v.DEFAULT_PRIOR.read_text(encoding='utf-8'))
 priors={r['document']['record_id']:r for r in old['results']};tax=v.base.load_taxonomy(v.old.earlier.support.previous.p.p.v.legacy.TAXONOMY)
 eligible=[r for r in p['results'] if any(c['phase'].endswith('v89') and c['status']!='success' for c in r['calls'])]
 print(json.dumps({'retry_sources':len(eligible),'success_cache_reused':True,'workers':2,'global_cap':10}),flush=True)
 runner=v.ApiRunner(a.output_dir,10,key=os.getenv('YS_LLM_API_KEY'));updated={}
 def work(r):return v.process(priors[r['document']['record_id']],tax,p['business'],runner,a.output_dir)
 with ThreadPoolExecutor(max_workers=2) as pool:
  for f in as_completed([pool.submit(work,r) for r in eligible]):
   rr=f.result();updated[rr['document']['record_id']]=rr
   print(json.dumps({'retry_complete':len(updated),'total':len(eligible),'record':rr['document']['record_id'],'pending':len(rr['pending_units'])},ensure_ascii=False),flush=True)
 results=[updated.get(r['document']['record_id'],r) for r in p['results']]
 new=v.base.export(a.output_dir,results,p['sampling'],tax,p['business'],runner,'api',True)
 new['summary'].update(version=v.VERSION,pipeline='MapReduce/H＋字段补全；只恢复瞬时错误来源，成功请求复用',note=p['summary']['note'])
 new['delivery_changes']=[c for r in results for c in r.get('repair_changes',[])];new['new_test_status']=dict(p['new_test_status'],new=v.metrics(results),transport_resume_sources=len(eligible))
 new['tables']['未完成待核']=[q for r in results for q in r.get('pending_units',[])];new['execution_manifest']=p.get('execution_manifest',{})
 v.save_json(fn,new);print(json.dumps(new['new_test_status'],ensure_ascii=False),flush=True)
if __name__=='__main__':main()
