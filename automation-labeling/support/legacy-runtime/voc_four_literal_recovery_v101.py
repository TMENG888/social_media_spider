"""Exact field aliases only. No tag, role verdict, quote or source changes."""
import argparse
import copy
import json
import sys
from collections import defaultdict,Counter
import voc_four_projects_v101 as p
from product800_evidence import normalize_role as ellipsis_role

ALIASES={'author_name':'作者名字','publisher_name':'作者名字','username':'作者名字',
 'author_url':'作者主页链接','author_homepage':'作者主页链接','publisher_url':'作者主页链接',
 'comment_content':'评论内容','comment_text':'评论内容','post_title':'文章标题','title':'文章标题','platform':'平台',
 'post_content':'文章内容','article_content':'文章内容','article_title':'文章标题',
 'video_content':'文章视频内容','image_info':'文章图片信息','post_tags':'文章标签'}

def normalize_role(raw,fields):
 result=copy.deepcopy(raw);audit=[]
 for e in result.get('evidence',[]):
  old=e.get('field');target=ALIASES.get(old)
  if old=='content':
   matches=[f for f in ('评论内容','文章内容') if f in fields and e.get('quote') and e['quote'] in fields[f]]
   target=matches[0] if len(matches)==1 else None
  if old not in fields and target in fields and e.get('quote') and e['quote'] in fields[target]:
   e['field']=target;audit.append({'action':'字段名别名，逐字引文不变','from':old,'to':target,'quote':e['quote']})
 result,more=ellipsis_role(result,fields);return result,audit+more

def choose_publisher(existing,raw,fields):
 """Reuse one already-grounded Qwen source verdict, never synthesize a role."""
 if existing is not None:
  errors=p.product.role_errors(existing,fields)
  return copy.deepcopy(existing),errors,[{'action':'保留同源已保存Qwen发布者裁决；不重复判定角色','no_new_role_decision':True}]
 normalized,audit=normalize_role(raw,fields)
 return normalized,p.product.role_errors(normalized,fields),audit

def literal_project_references(fields,projects):
 """Offer real identity substrings for copying; do not assign project labels."""
 options=[];seen=set()
 for project in projects:
  for field in ('source','title','parent','parent_title'):
   text=fields.get(field) or ''
   for alias in project['aliases']:
    if alias and alias in text:
     key=(project['id'],field,alias)
     if key not in seen:
      seen.add(key);options.append({'project_id':project['id'],'context_source':field,'quote':alias})
 return options

def repair_request_plan(pending):
 """Prepared only: one unfinished unit, using the runner's existing full cap."""
 return {'units':copy.deepcopy(pending[:1]),
  'phase':'专题二四项目单切片补标与归属自检-v101-完整输出',
  'max_output_tokens':p.v.b.MAX_OUTPUT_TOKENS}

def repair_schema(items,catalog,fields,references):
 """Constrain field names and identity quotes to actual source options only."""
 schema=p.schema_for(items,catalog)
 publisher=schema['properties']['publisher']['properties']
 publisher['evidence']['items']['properties']['field']={'type':'string','enum':list(fields)}
 if references:
  identity=schema['properties']['units']['items']['properties']['views']['items']['properties']['labels']['items']['properties']['project_identity']['properties']
  # The legacy schema deliberately shares one text dict across several fields.
  # Replace this leaf; mutating it would also constrain tag ids and summaries.
  identity['quote']={'type':'string','enum':list(dict.fromkeys(r['quote'] for r in references))}
  locations=list(dict.fromkeys(r['context_source'] for r in references if r.get('context_source')))
  if locations:identity['context_source']={'type':'string','enum':locations}
 return schema

def prepare():
 tax=p.read(p.OUT/'taxonomy.json');idx={t['tag_id']:t for t in tax};state=p.read(p.OUT/'run_status.json')
 failed={r['record_id']:(f,r) for f in (p.OUT/'results').glob('*.json') if (r:=p.read(f))['state']=='retry_required' and r['record_id'] not in state['active_sources']}
 calls=defaultdict(list)
 for f in (p.OUT/'calls').glob('*.json'):
  c=p.read(f)
  if c['metrics']['record_id'] in failed and c['metrics']['status']=='success' and isinstance(c.get('response'),dict) and 'units' in c['response']:
   calls[c['metrics']['record_id']].append((f.stat().st_mtime,f,c))
 candidates=[]
 for rid,(file,r) in failed.items():
  assert r['signature']==p.signature(r['document'],tax)
  fields=p.own_fields(r['document']);catalog=p.v.supplement.evidence_catalog(r['units']);units={u['unit_id']:u for u in r['units']}
  first_role=r['publisher'] if r.get('publisher') and not p.product.role_errors(r['publisher'],fields) else None
  fixes={};role=None;proof=[]
  for _,f,c in sorted(calls[rid]):
   raw=c['response'];fixed_role,audit=normalize_role(raw['publisher'],fields)
   usable=first_role or (fixed_role if not p.product.role_errors(fixed_role,fields) else None)
   if usable is None:continue
   if first_role is None:first_role=usable
   counts=Counter(u['unit_id'] for u in raw['units'])
   for unit in raw['units']:
    uid=unit['unit_id']
    if uid not in r['unfinished_units'] or uid in fixes or counts[uid]!=1:continue
    # A drained worker may have saved a newer successful unit before its
    # source summary was refreshed. Never replace that immutable checkpoint.
    if p.path_for('unit_results',rid+'|'+uid).exists():continue
    from voc_four_single_truth_v101 import derive_unit
    try:normal=derive_unit(unit)
    except (ValueError,KeyError,TypeError):continue
    if p.validate_unit(normal,units[uid],catalog,r['document'],idx):continue
    fixes[uid]=normal;role=usable
    proof.append({'unit_id':uid,'request_key':c['metrics']['request_key'],'call_file':str(f),'call_sha256':p.v.sha(f),
     'literal_role_field_aliases':audit,'reused_existing_source_role':r.get('publisher')==usable,
     'unit_semantics_unchanged':True,'no_api_calls':True})
  if fixes:candidates.append({'record_id':rid,'source_result':str(file),'source_result_sha256':p.v.sha(file),
   'source_signature':r['signature'],'new_outcomes':fixes,'publisher':role,'proof':proof,
   'will_complete_source':set(r['outcomes'])|set(fixes)==set(units)})
 result={'prepared':True,'new_api_calls':0,'no_tag_or_role_verdict_changes':True,'candidates':candidates,
  'source_count':len(candidates),'unit_count':sum(len(c['new_outcomes']) for c in candidates),'complete_source_count':sum(c['will_complete_source'] for c in candidates)}
 p.save('literal_recovery_candidates.json',result);return result

def reconcile_saved_units():
 """Refresh retry summaries from signed, validated formal Qwen checkpoints."""
 if p.LOCK.exists() or (p.OUT/'finalize_v101/instance.lock').exists():raise RuntimeError('Drain both owners first')
 from verify_voc_four_projects_v101 import model_response_index
 tax=p.read(p.OUT/'taxonomy.json');idx={t['tag_id']:t for t in tax}
 records=[(f,p.read(f)) for f in (p.OUT/'results').glob('*.json')]
 records=[(f,r) for f,r in records if r['state']=='retry_required' and any(
  u['unit_id'] not in r['outcomes'] and p.path_for('unit_results',r['record_id']+'|'+u['unit_id']).exists() for u in r['units'])]
 model_units,model_publishers=model_response_index([r for f,r in records]);applied=[]
 for file,r in records:
  if r['signature']!=p.signature(r['document'],tax):raise RuntimeError('Source signature differs')
  cat=p.v.supplement.evidence_catalog(r['units']);added=[]
  for item in r['units']:
   uid=item['unit_id'];saved=p.path_for('unit_results',r['record_id']+'|'+uid)
   if uid in r['outcomes'] or not saved.exists():continue
   b=p.read(saved)
   if b['signature']!=p.digest([r['signature'],item]):raise RuntimeError('Saved unit signature differs')
   if p.validate_unit(b['unit'],item,cat,r['document'],idx):raise RuntimeError('Saved unit contract invalid')
   if p.product.role_errors(b['publisher'],p.own_fields(r['document'])):raise RuntimeError('Saved publisher invalid')
   if p.digest(b['unit']) not in model_units[r['record_id']][uid]:raise RuntimeError('Saved unit lacks formal Qwen provenance')
   if p.digest(b['publisher']) not in model_publishers[r['record_id']]:raise RuntimeError('Saved publisher lacks formal Qwen provenance')
   if not r.get('publisher'):r['publisher']=b['publisher']
   r['outcomes'][uid]=b['unit'];added.append({'unit_id':uid,'file':str(saved),'sha256':p.v.sha(saved)})
  r['unfinished_units']=[u['unit_id'] for u in r['units'] if u['unit_id'] not in r['outcomes']]
  r['state']='retry_required' if r['unfinished_units'] else 'accepted' if any(u['views'] for u in r['outcomes'].values()) else 'excluded'
  r.setdefault('saved_unit_reconciliation_proof',[]).extend(added)
  p.atomic_save_json(file,r);applied.append({'record_id':r['record_id'],'state':r['state'],'units':added})
 p.save('saved_unit_reconciliation.json',{'new_api_calls':0,'successful_unit_files_unchanged':True,'items':applied})
 return applied

def apply():
 if p.LOCK.exists() or (p.OUT/'finalize_v101/instance.lock').exists():raise RuntimeError('Generation/finalization live; prepare only, do not apply')
 reconcile_saved_units()
 x=prepare();applied=[]
 for c in x['candidates']:
  file=c['source_result'];r=p.read(file)
  if r['state']!='retry_required' or p.v.sha(file)!=c['source_result_sha256']:raise RuntimeError('Recovery source changed')
  if r['signature']!=c['source_signature']:raise RuntimeError('Recovery source signature differs')
  old_publisher=r['publisher'];r['publisher']=old_publisher or c['publisher'];items={u['unit_id']:u for u in r['units']}
  for uid,outcome in c['new_outcomes'].items():
   target=p.path_for('unit_results',r['record_id']+'|'+uid)
   if target.exists():
    existing=p.read(target)
    if existing['signature']!=p.digest([r['signature'],items[uid]]) or existing['unit']!=outcome:raise RuntimeError('Existing unit cache differs; never overwrite')
   else:p.atomic_save_json(target,{'signature':p.digest([r['signature'],items[uid]]),'unit':outcome,'publisher':r['publisher'],
     'literal_recovery_proof':[a for a in c['proof'] if a['unit_id']==uid]})
   if uid in r['outcomes']:raise RuntimeError('Cannot replace a successful unit')
   r['outcomes'][uid]=outcome
  r['unfinished_units']=[u['unit_id'] for u in r['units'] if u['unit_id'] not in r['outcomes']]
  r['state']='retry_required' if r['unfinished_units'] else 'accepted' if any(u['views'] for u in r['outcomes'].values()) else 'excluded'
  r['literal_recovery_proof']=c['proof'];p.atomic_save_json(file,r);applied.append({'record_id':r['record_id'],'state':r['state'],'units':len(c['new_outcomes'])})
 p.save('literal_recovery_applied.json',{'new_api_calls':0,'items':applied});return x

if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8');a=argparse.ArgumentParser();a.add_argument('--apply',action='store_true');args=a.parse_args();r=apply() if args.apply else prepare();print(json.dumps({k:v for k,v in r.items() if k!='candidates'},ensure_ascii=False))
