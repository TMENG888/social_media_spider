"""Gated topic1-only batch entry point. No default paid execution.

Uses the same frozen process_document/identity workflow as A/B/C. A first
10-source pilot is included in, not additional to, the final 300 articles.
"""
import sys,os,json,hashlib,argparse,datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
sys.dont_write_bytecode=True;sys.stdout.reconfigure(encoding='utf8')
R=Path(__file__).parent
sys.path.insert(0,str(R/'production_snapshot'))
import delivery_v4 as api
import topic1_semantic_pipeline as pipeline
import topic1_identity as identity
import version_contract

def read(p):return json.loads(Path(p).read_text(encoding='utf8'))
def save(p,x):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf8');tmp.replace(p)
def validate_semantic_release(review,version,results_hashes):
    assert review.get('version')==version,'Semantic review version mismatch'
    assert review.get('reviewer_type') in ['codex','business_human'],'Semantic reviewer type required'
    assert review.get('approved_for_pilot') is True and review.get('critical_errors')==0,'Semantic review has not approved a pilot'
    assert review.get('source_counts')=={'A':10,'B':10,'C':10},'Semantic review must cover all three complete reference sets'
    assert review.get('result_sha256')==results_hashes,'Semantic review must bind the actual A/B/C outputs'
    assert isinstance(review.get('known_limitations'),list),'Known limitations must be explicit'
    return review
def assert_gates(version,count):
    frozen=version_contract.verify_frozen()
    if frozen['version']!=version:raise ValueError('Batch version is not the frozen version')
    policy=read(R/'acceptance_policy.json')
    for batch in 'ABC':
        run=R/f'run_{version}';e=read(run/f'evaluation_{batch}.json');a=read(run/f'audit_{batch}.json')
        assert e['model_sources']==e['reference_sources']==10
        assert e['source_tag']['precision']>=policy['source_tag_precision_min']
        assert e['source_tag']['recall']>=policy['source_tag_recall_min']
        assert not e['structural_errors'] and not a['structural_errors']
        assert e['duplicate_slices']==e['empty_practice']==0 and not a['summary_numeric_review']
    assert (R/f'semantic_review_C_{version}.md').exists(),'C documented semantic review is required'
    validate_semantic_release(read(R/f'run_{version}/semantic_release.json'),version,
        {b:version_contract.sha(R/f'run_{version}/{b}_results.json') for b in 'ABC'})
    if count>10:
        pilot=read(R/'batch300'/version/'pilot_review.json')
        assert pilot['approved_for_remaining_batch'] and pilot['critical_errors']==0
        assert pilot.get('reviewer_type') in ['codex','business_human'],'Reviewer type must be explicit; Codex review is not human sign-off'
        expected={d['record_id'] for d in read(R/'batch300/documents.json')[:10]}
        assert pilot.get('sources_reviewed')==10 and set(pilot['source_result_hashes'])==expected,'Pilot must cover every one of the fixed first ten sources'
        assert pilot.get('source_input_sha256')==version_contract.sha(R/'batch300/documents.json'),'Review must bind the actual input population'
        for rid,digest in pilot['source_result_hashes'].items():
            assert version_contract.sha(R/'batch300'/version/'sources'/f'{rid}.json')==digest
    return frozen
def validate_result(result,tax):
    d=result['document'];parts=result['semantic_partition'];pos=0;known={t['tag_id'] for t in tax}
    for u in parts:
        assert u['start']==pos and u['end']>pos and d['text'][pos:u['end']]==u['text']
        pos=u['end'];ids=[x['tag_id'] for x in u['labels']]
        assert len(ids)==len(set(ids)) and set(ids)<=known
        for p in u['labels']:assert p['quote'] and p['quote'] in u['text']
        if u['deliver']:
            assert u['practice'].strip()
            assert not pipeline.lexical_fidelity_issues(u['text'],u['practice'])
    assert pos==len(d['text'])
    checks=[c for g in result['label_audit']['table_audit'] for c in g['result']['checks']]
    assert len(checks)==len(known) and {c['tag_id'] for c in checks}==known
    assert len(result['rows'])==sum(u['deliver'] for u in parts)
    assert len({(r['起点'],r['终点']) for r in result['rows']})==len(result['rows'])
    return {'source_id':d['source_id'],'partition_units':len(parts),'delivery_units':len(result['rows']),
            'summary_fallbacks':sum(bool(u.get('summary_fallback')) for u in parts),'structural_errors':0}
def main():
    p=argparse.ArgumentParser();p.add_argument('--version',required=True);p.add_argument('--count',type=int,choices=[10,300],default=10)
    p.add_argument('--execute',action='store_true');args=p.parse_args()
    frozen=assert_gates(args.version,args.count)
    docs=read(R/'batch300/documents.json')
    assert len(docs)==300 and all(d['topic']==api.T1 and d['kind']=='文章' for d in docs)
    if not args.execute:
        print(json.dumps({'validated_only':True,'planned':args.count,'version':args.version},ensure_ascii=False));return
    tax=read(R/'inputs/taxonomy.json');business=read(R/'inputs/brand_dictionary.json')
    out=R/'batch300'/args.version;out.mkdir(exist_ok=True);lock=out/'batch.lock'
    fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.write(fd,str(os.getpid()).encode());os.close(fd)
    runner=api.ApiRunner(R/'api_cache',concurrency=6)
    seal_hash=api.digest(frozen['files']);input_hash=version_contract.sha(R/'batch300/documents.json')
    done={};errors=[];audits={}
    def work(d):
        path=out/'sources'/f'{d["record_id"]}.json';signature=api.digest({'frozen_code':seal_hash,'doc':d,'model':runner.model})
        if path.exists():
            old=read(path)
            if old['signature']==signature:
                validate_result(old['result'],tax);return old['result']
        result=pipeline.process_document(d,tax,business,runner);result=identity.process(result,business,runner)
        validate_result(result,tax);save(path,{'signature':signature,'result':result});return result
    try:
        save(out/'execution.json',{'version':args.version,'planned':args.count,'input_sha256':input_hash,'frozen_code_sha256':seal_hash,'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'production_default_changed':False})
        with ThreadPoolExecutor(max_workers=3) as pool:
            fs={pool.submit(work,d):d for d in docs[:args.count]}
            for f in as_completed(fs):
                d=fs[f]
                try:
                    result=f.result();done[d['record_id']]=result;audits[d['record_id']]=validate_result(result,tax)
                except Exception as e:errors.append({'record_id':d['record_id'],'error_type':type(e).__name__,'error':str(e)[:500]})
                status={'version':args.version,'completed':len(done),'planned':args.count,'errors':errors,'last_source':d['record_id']}
                save(out/'status.json',status);print(json.dumps(status,ensure_ascii=False),flush=True)
        save(out/f'results_{args.count}.json',[done[d['record_id']] for d in docs[:args.count] if d['record_id'] in done])
        save(out/f'audit_{args.count}.json',{'sources':list(audits.values()),'errors':errors})
        save(out/f'calls_{args.count}.json',{'model':runner.model,'calls':runner.calls,'errors':errors})
        if errors:raise RuntimeError('Batch contains failed sources; successful caches retained for exact resume')
    finally:lock.unlink(missing_ok=True)
if __name__=='__main__':main()
