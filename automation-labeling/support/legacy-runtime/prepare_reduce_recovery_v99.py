"""Prepare failed-stage candidates offline; does not accept, run API, or alter generation."""
import copy,json,re,sys
import voc_batch_v99 as v
from structured_response_validation_v58 import issues
from bounded_visible_contract_v60 import contract

def normalize_quote(source,unit):
    original=unit['start_quote'];hits=[m.start() for m in re.finditer('(?='+re.escape(original)+')',source)]
    ordinal=unit['start_occurrence']
    if not 1<=ordinal<=len(hits):return None,None
    start=hits[ordinal-1];short=original[:35]
    short_hits=[m.start() for m in re.finditer('(?='+re.escape(short)+')',source)]
    if not short or start not in short_hits:return None,None
    fixed=copy.deepcopy(unit);fixed['start_quote']=short;fixed['start_occurrence']=short_hits.index(start)+1
    return fixed,{'original_quote':original,'normalized_quote':short,'source_start':start,
        'original_occurrence':ordinal,'normalized_occurrence':fixed['start_occurrence'],
        'rule':'Only shorten literal location anchor; same source character start; no semantic boundary move'}

def main():
    records=[v.read(p) for p in (v.OUT/'revisions'/v.VERSION/'results').glob('*.json')]
    failed={r['record_id']:r for r in records if r['state']=='pending_exception'}
    calls=[]
    for p in (v.OUT/'calls').glob('*.json'):
        try:c=v.read(p)
        except (OSError,json.JSONDecodeError):continue
        m=c.get('metrics',{})
        if m.get('record_id') in failed and m.get('phase')=='Reduce全文语义边界-v76-结构恢复':calls.append((p,c))
    output=[];unrecoverable=[]
    for path,c in calls:
        m=c['metrics'];rid=m['record_id'];doc=failed[rid]['document'];raw=c.get('response')
        schema=contract(v.partition.boundary.SCHEMA,{})
        problems=issues(raw,schema)
        if not problems or any(not e.endswith('.start_quote: 文本长度违反请求结构') for e in problems):
            unrecoverable.append({'record_id':rid,'source_signature':failed[rid]['signature'],
                'reason':'Not a literal-anchor-only structure error; preserve semantic uncertainty or other contract issues',
                'errors':problems,'accepted_for_generation_or_statistics':False})
            continue
        fixed=copy.deepcopy(raw);audit=[]
        for n,u in enumerate(raw['units']):
            if len(u['start_quote'])<=35:continue
            replacement,event=normalize_quote(doc['text'],u)
            if replacement is None:break
            fixed['units'][n]=replacement;audit.append(event)
        remaining=issues(fixed,schema)
        if remaining:
            unrecoverable.append({'record_id':rid,'source_signature':failed[rid]['signature'],
                'reason':'Literal anchor could not be shortened at a verified source position',
                'errors':remaining,'accepted_for_generation_or_statistics':False})
            continue
        positions,errors=v.partition.boundary.locate(doc['text'],fixed)
        if errors:
            unrecoverable.append({'record_id':rid,'source_signature':failed[rid]['signature'],
                'reason':'Short anchor still fails source location/coverage validation',
                'errors':errors,'accepted_for_generation_or_statistics':False})
            continue
        plan,segments,errors=v.partition.build_plan(doc['text'],fixed,v.quote_partition)
        if errors:
            unrecoverable.append({'record_id':rid,'source_signature':failed[rid]['signature'],
                'reason':'Short anchor still fails lossless source partition validation',
                'errors':errors,'accepted_for_generation_or_statistics':False})
            continue
        output.append({'record_id':rid,'source_signature':failed[rid]['signature'],
            'original_call_file':str(path),'original_call_sha256':v.sha(path),
            'original_schema_errors':problems,'original_response':raw,'location_only_candidate':fixed,
            'position_audit':audit,'positions':positions,'plan':plan,'segments':segments,
            'status':'offline_candidate_requires_full_source_semantic_boundary_review',
            'accepted_for_generation_or_statistics':False,
            'reason':'Literal anchor formatting is recoverable, but schema/literal correctness does not prove semantic object partition correctness'})
    v.save('reduce_recovery_candidates.json',{'records':output,'unrecoverable_without_new_adjudication':unrecoverable,
        'network_calls':0,'successful_sources_rerun':False,
        'original_calls_results_and_code_unchanged':True})
    print(json.dumps({'prepared_candidate_sources':len(output),'record_ids':[r['record_id'] for r in output],
        'unrecoverable_without_new_adjudication':unrecoverable,'accepted_sources':0,'network_calls':0},ensure_ascii=False))

if __name__=='__main__':sys.stdout.reconfigure(encoding='utf-8');main()
