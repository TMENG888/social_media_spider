"""Read-only by default. --apply requires saved authorization and a drained old PID.

Copies to a separate revision only. Never overwrites original generation files,
never accepts a pending/partial unit as a completed source, never runs an API.
"""
import argparse,copy,ctypes,os,sys,time
from pathlib import Path
from collections import Counter
import voc_batch_v99 as v
import voc_repair_overlay_v994 as o
from voc_metadata_completion_v99 import record_issues

OLD_VERSION='voc-v99.3-latest-source-closed-loop-20261014'

def source_signature(doc,reuse,taxonomy,version,script_sha):
    return v.b.digest({'version':version,'source':v.stable_source(doc),'score':doc['row'].get('情绪评分'),
        'taxonomy':taxonomy,'script_sha256':script_sha,'reuse':reuse})

def old_pid_live(pid):
    if sys.platform!='win32':
        try:os.kill(pid,0);return True
        except ProcessLookupError:return False
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[ctypes.c_uint32,ctypes.c_int,ctypes.c_uint32];kernel.OpenProcess.restype=ctypes.c_void_p
    kernel.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint32)]
    kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    handle=kernel.OpenProcess(0x1000,False,pid)
    if not handle:
        if ctypes.get_last_error()==87:return False
        raise RuntimeError('Cannot establish old PID exit safely')
    code=ctypes.c_uint32()
    try:
        if not kernel.GetExitCodeProcess(handle,ctypes.byref(code)):raise RuntimeError('PID liveness query failed')
        return code.value==259
    finally:kernel.CloseHandle(handle)

def build_reuse_plan(documents,reuse,taxonomy,held,old_root,new_root,old_sha,new_sha):
    planned=[];stats=Counter();issues=[]
    index={t['tag_id']:t for t in taxonomy}
    for doc in documents:
        rid=doc['record_id'];name=v.b.digest(rid)+'.json'
        old_result=old_root/'results'/name;old_seed=old_root/'seeds'/name
        if not old_result.exists() and not old_seed.exists():continue
        source_sig=source_signature(doc,reuse[rid],taxonomy,OLD_VERSION,old_sha)
        new_sig=source_signature(doc,reuse[rid],taxonomy,o.VERSION,new_sha)
        record=v.read(old_result) if old_result.exists() else None
        if record and record.get('signature')!=source_sig:
            issues.append({'record_id':rid,'issue':'Original terminal source signature mismatch'});continue
        seed=v.read(old_seed) if old_seed.exists() else None
        if seed is not None:
            if v.stable_source(seed['document'])!=v.stable_source(doc):
                issues.append({'record_id':rid,'issue':'Original seed source context mismatch'});continue
            copied_seed=copy.deepcopy(seed)
            copied_seed['stage_reuse_v994']={'source':str(old_seed),'sha256':v.sha(old_seed),'unchanged_source_and_dictionary':True}
            planned.append((new_root/'seeds'/name,copied_seed));stats['seeds']+=1
            try:_,items,_=v.repair_targets(seed,taxonomy)
            except (AssertionError,KeyError,ValueError) as e:
                issues.append({'record_id':rid,'issue':'Original source partition/units invalid: '+type(e).__name__});continue
            for item in items:
                unitname=v.b.digest([rid,item['unit_id']])+'.json';old_unit=old_root/'repairs'/unitname
                if not old_unit.exists():continue
                unit_record=v.read(old_unit);expected=v.b.digest({'source_signature':source_sig,'item':item})
                if unit_record.get('signature')!=expected:
                    issues.append({'record_id':rid,'unit_id':item['unit_id'],'issue':'Original unit signature mismatch'});continue
                outcome=unit_record['outcome']
                if outcome['state'] not in {'accepted','excluded'} or rid in held:continue
                if outcome['state']=='accepted' and v.row_problems(outcome['row'],outcome['trace'],seed['document'],index):
                    issues.append({'record_id':rid,'unit_id':item['unit_id'],'issue':'Approved unit field/evidence identity mismatch'});continue
                if outcome['state']=='accepted':
                    history=outcome.get('history') or []
                    draft=history[-1].get('draft') if history else None
                    metadata_issues=(o.metadata_contract_issues(draft) if isinstance(draft,dict) and draft.get('decision')=='supported'
                                     else ['原始supported metadata回复证据缺失'])
                    if metadata_issues:
                        # Keep saved, verified sibling labels as repair context, not
                        # an accepted unit. Never rerun partitioning or lose tags.
                        uid=item['unit_id']
                        row=next((r for r in (record or {}).get('rows',[]) if r['unit_id']==uid),outcome['row'])
                        trace=next((t for t in (record or {}).get('traces',[]) if t['unit_id']==uid),outcome['trace'])
                        if v.row_problems(row,trace,seed['document'],index):
                            issues.append({'record_id':rid,'unit_id':uid,'issue':'Retained label context does not reconcile'});continue
                        copied_seed['rows']=[r for r in copied_seed.get('rows',[]) if r['unit_id']!=uid]+[copy.deepcopy(row)]
                        copied_seed['traces']=[t for t in copied_seed.get('traces',[]) if t['unit_id']!=uid]+[copy.deepcopy(trace)]
                        copied_seed.setdefault('metadata_completion_pending_units',[]).append({
                            'unit_id':uid,'source_quote':row['原始摘录'],'issues':metadata_issues,
                            'original_repair_path':str(old_unit),'original_repair_sha256':v.sha(old_unit),
                            'verified_labels_retained_not_terminal':True})
                        stats['metadata_incomplete_units_not_reused_as_success']+=1
                        continue
                copied=copy.deepcopy(unit_record);copied['signature']=v.b.digest({'source_signature':new_sig,'item':item})
                copied['stage_reuse_v994']={'source':str(old_unit),'sha256':v.sha(old_unit),'original_success_retained':True}
                planned.append((new_root/'repairs'/unitname,copied));stats['completed_'+outcome['state']+'_units']+=1
        if record and record['state'] in {'accepted','excluded','pending_score'} and rid not in held:
            if record['state']=='accepted':
                def load_old_metadata(source_id,unit_id):
                    original=old_root/'repairs'/(v.b.digest([source_id,unit_id])+'.json')
                    return v.read(original) if original.exists() else None
                metadata_evidence_issues=record_issues(record,load_old_metadata,{})
                if seed is not None:
                    by_unit={m['unit_id']:m for m in copied_seed.get('metadata_completion_pending_units',[])}
                    for metadata_issue in metadata_evidence_issues:
                        uid=metadata_issue['unit_id']
                        if uid is None:continue
                        row=next(r for r in record['rows'] if r['unit_id']==uid)
                        trace=next(t for t in record['traces'] if t['unit_id']==uid)
                        copied_seed['rows']=[r for r in copied_seed.get('rows',[]) if r['unit_id']!=uid]+[copy.deepcopy(row)]
                        copied_seed['traces']=[t for t in copied_seed.get('traces',[]) if t['unit_id']!=uid]+[copy.deepcopy(trace)]
                        if uid not in by_unit:
                            by_unit[uid]={'unit_id':uid,'source_quote':row['原始摘录'],'issues':[],
                                'verified_labels_retained_not_terminal':True}
                        by_unit[uid]['issues'].append(metadata_issue['reason']+'；字段='+str(metadata_issue['field']))
                    if by_unit:copied_seed['metadata_completion_pending_units']=list(by_unit.values())
                if seed is None or copied_seed.get('metadata_completion_pending_units'):
                    stats['metadata_incomplete_terminal_sources_not_reused']+=1;continue
                if record.get('pending') or len(record['rows'])!=len(record['traces']) or not record['rows']:
                    issues.append({'record_id':rid,'issue':'Accepted source is not complete'});continue
                if any(v.row_problems(row,trace,doc,index) for row,trace in zip(record['rows'],record['traces'])):
                    issues.append({'record_id':rid,'issue':'Accepted source fields do not reconcile'});continue
            copied=copy.deepcopy(record);copied['signature']=new_sig
            copied['stage_reuse_v994']={'source':str(old_result),'sha256':v.sha(old_result),'original_success_retained':True}
            planned.append((new_root/'results'/name,copied));stats['terminal_'+record['state']+'_sources']+=1
    return planned,stats,issues

def main():
    p=argparse.ArgumentParser();p.add_argument('--apply',action='store_true');a=p.parse_args()
    launcher=v.read(v.OUT/'launcher_identity.json')
    if launcher['annotation_script_sha256']!=o.BASE_SHA256:raise RuntimeError('Launcher is not the validated v99.3 generation')
    if v.sha(v.__file__)!=o.BASE_SHA256:raise RuntimeError('Original running implementation changed')
    if a.apply:
        approval=v.read(v.OUT/'control'/'approval_to_switch_v994.json')
        if not approval.get('approved'):raise RuntimeError('No saved explicit user switch authorization')
        if (v.OUT/'control'/'instance.lock').exists() or old_pid_live(launcher['pid']):
            raise RuntimeError('Old driver not fully drained; no stage reuse applied')
    for frozen in v.read(v.OUT/'manifest.json')['frozen_inputs']:
        if v.sha(frozen['snapshot'])!=frozen['sha256']:raise RuntimeError('Frozen input changed')
    docs=v.read(v.OUT/'candidate_documents.json');reuse={r['record_id']:r for r in v.read(v.OUT/'reuse_manifest.json')}
    tax=v.read(v.OUT/'taxonomy.json');held={h['record_id'] for h in v.read(v.OUT/'independent_quality_holds.json')['holds'] if h['status']!='resolved'}
    old_root=v.OUT/'revisions'/OLD_VERSION;new_root=v.OUT/'revisions'/o.VERSION
    plan,stats,issues=build_reuse_plan(docs,reuse,tax,held,old_root,new_root,o.BASE_SHA256,v.sha(o.__file__))
    report={'passed':not issues,'mode':'applied' if a.apply else 'read_only_preflight','counts':dict(stats),
        'issues':issues,'original_stage_files_modified':False,'network_calls':0,'quality_held_sources_not_reused':sorted(held),
        'old_primary_pid':launcher['pid'],'new_version':o.VERSION,'new_overlay_sha256':v.sha(o.__file__),'observed_at':time.time()}
    if a.apply:
        if issues:raise RuntimeError('Stage signature validation failed; no reuse applied')
        for target,value in plan:
            if target.exists():
                if v.read(target)!=value:raise RuntimeError('Existing isolated stage differs; no overwrite: '+str(target))
        # Validate all collisions before any write; interruption can resume exact copies safely.
        for target,value in plan:
            if not target.exists():v.b.save_json(target,value)
    v.save('stage_reuse_v994_applied.json' if a.apply else 'stage_reuse_v994_preflight.json',report)
    print(v.b.dumps(report))

if __name__=='__main__':sys.stdout.reconfigure(encoding='utf-8');main()
