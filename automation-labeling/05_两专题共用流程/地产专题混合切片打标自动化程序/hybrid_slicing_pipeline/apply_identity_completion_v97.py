"""Add stage 05 identity completion without invalidating saved v96 stages 01-04."""
import argparse
import json
import os
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import delivery_v4 as b
import identity_completion_v97 as identity
from gym_policy_v96 import VERSION as POLICY_VERSION
from resume_limited_v96 import InstanceLock,assert_no_generator
from safe_concurrency_v96 import Governor,ControlledPost
from token_cost_report_v93 import report

def complete(directory,taxonomy_path,concurrency=8,compose=True):
    sample=json.loads((directory/'sample.json').read_text(encoding='utf-8'));docs=sample['documents']
    assert len(docs)==1956 and len({d['record_id'] for d in docs})==1956
    assert Counter((d['topic'],d['kind']) for d in docs)==Counter({(b.T1,'文章'):500,(b.T2,'文章'):500,(b.T2,'评论'):956})
    taxonomy=b.load_taxonomy(taxonomy_path);business=b.load_business()
    signature=b.digest({'code':Path(identity.__file__).read_text(encoding='utf-8'),'business':business})
    control=directory/'identity_v97_control';runner=b.ApiRunner(directory,concurrency)
    gov=Governor(concurrency,stop=lambda:(control/'soft_stop.request').exists() or runner.fatal.is_set())
    b.post_json=ControlledPost(b.post_json,gov,control,b.save_json)
    start=time.time();done={}
    def one(doc):
        input_path=directory/'stages'/'04_final'/(b.digest(doc['record_id'])+'.json')
        if not input_path.is_file():raise ValueError('Missing v96 final source: '+doc['record_id'])
        old=json.loads(input_path.read_text(encoding='utf-8'))['result'];assert old['document']==doc
        key=b.digest({'identity_code':signature,'input':old})
        output=directory/'stages'/'05_identity_v97'/(b.digest(doc['record_id'])+'.json')
        if output.exists():
            prior=json.loads(output.read_text(encoding='utf-8'))
            if prior.get('identity_signature')==key:return prior['result']
        result=identity.process(old,business,runner)
        b.save_json(output,{'identity_signature':key,'result':result});return result
    with InstanceLock(control):
        assert_no_generator(directory)
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures=[pool.submit(one,d) for d in docs]
            for future in as_completed(futures):
                r=future.result();done[r['document']['record_id']]=r
                if len(done)%10==0 or len(done)==len(docs):
                    status={'version':identity.VERSION,'pid':os.getpid(),'processed_sources':len(done),'planned_sources':len(docs),
                            'elapsed_seconds':round(time.time()-start),'state':'complete' if len(done)==len(docs) else 'running'}
                    b.save_json(directory/'identity_progress_v97.json',status);print(b.dumps(status),flush=True)
        results=[done[d['record_id']] for d in docs]
        changes=[c for r in results for c in r['identity_completion_v97']['changes']]
        remaining=[c for r in results for c in r['identity_completion_v97']['remaining']]
        b.save_json(directory/'identity_summary_v97.json',{'version':identity.VERSION,'processed_sources':len(results),
                    'filled_fields':len(changes),'remaining_categories':Counter(c['category'] for c in remaining),
                    'negative_review_confirmed':sum(c.get('negative_review_confirmed',False) for c in remaining),
                    'remaining':remaining,'changes':changes,'human_gold_standard':False})
        if compose:
            # Original stage results and signatures are never rewritten. Rebuild
            # only the derived delivery JSON/CSVs from frozen successful sources.
            data=b.export(directory,results,sample['sampling'],taxonomy,business,runner,'api',True)
            data['summary'].update(version=identity.VERSION,planned_articles=1000,requested_articles_per_topic=500,bulk_source_complete=True)
            data['execution_manifest']={'requested_record_ids':[d['record_id'] for d in docs],'scope':'各专题500文章加全量关联评论','seed':20261008}
            data['supplement_status']={'sources':len(results),'fully_scanned_sources':sum(r['label_supplement_coverage']['all_branches_checked'] for r in results),
                'new_tags':sum(r['label_supplement_coverage']['new_confirmed_tags'] for r in results),'zero_miss_guarantee':False}
            data['delivery_changes']=[e for r in results for e in r.get('repair_changes',[])]
            data['current_run_token_cost']=report(directory)
            data['gym_policy']={'version':POLICY_VERSION,'label_id':'VOC-0377','instruction':next(t['instruction'] for t in taxonomy if t['tag_id']=='VOC-0377')}
            data['identity_completion']={'version':identity.VERSION,'filled_fields':len(changes),'remaining_fields':len(remaining),
                                        'zero_miss_guarantee':False,'human_gold_standard':False}
            b.save_json(directory/'delivery_results.json',data)
    return len(changes)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output-dir',type=Path,required=True);ap.add_argument('--taxonomy',type=Path,required=True)
    ap.add_argument('--concurrency',type=int,default=8,choices=range(1,11));ap.add_argument('--checkpoints-only',action='store_true');args=ap.parse_args()
    print(b.dumps({'filled_fields':complete(args.output_dir,args.taxonomy,args.concurrency,not args.checkpoints_only)}),flush=True)
