import json,hashlib,os
from pathlib import Path
from collections import Counter
base=Path('D:/Codex/outputs/01a1349d-c76e-7b63-be36-3c8e0766deef/20261014_发布者角色各50条盲测')
out=Path(os.environ.get('ROLE_TEST_OUTPUT',str(base)))
full=out!=base
load=lambda f:json.loads((out/f).read_text(encoding='utf-8'))
p=load('packets.json');raw={r['sample_id']:r for r in load('raw_samples.json')};ref={r['sample_id']:r for r in load('codex_reference.json')};qs={r['sample_id']:r for r in load('qwen_results.json' if full else 'qwen_results_normalized.json')}
freeze=load('reference_freeze.json')
assert hashlib.sha256((out/'codex_reference.json').read_bytes()).hexdigest()==freeze['reference_sha256']
assert set(ref)==set(qs)=={r['sample_id'] for r in p}
ev=lambda a:'\n'.join(f"{e.get('field','缺字段')}：{e.get('quote','缺引文')}" if isinstance(e,dict) else str(e) for e in a)
rows=[];diffs=[]
for s in p:
 sid=s['sample_id'];r=ref[sid];q=qs[sid];v=q['response'] or {};same=r['role']==v.get('role');record=raw[sid]
 rows.append([sid,s['dataset'],s['fields']['平台'],record['row']['id'],record['row']['文章id'],s['fields']['作者名字'],s['fields']['文章标题'],r['role'],v.get('role','请求失败'),'一致' if same else '不一致',r['reason'],v.get('reason','未取得合规响应'),ev(r['evidence']),ev(v.get('evidence',[])),'通过' if not q['validation_issues'] else '；'.join(q['validation_issues']),'是' if r['review_required'] or v.get('review_required') or not same or q['validation_issues'] else '否',record['row'].get('文章链接',''),','.join(s['truncated_fields']),'',''])
 if not same:diffs.append({'sample_id':sid,'name':s['fields']['作者名字'],'codex':r['role'],'qwen':v.get('role'),'qwen_reason':v.get('reason'),'codex_reason':r['reason']})
postreview={
 '1-11':'Qwen角色为普通，但理由末段改称身份不明，标签与理由矛盾；建议人工核验销售服务。',
 '1-23':'Codex专业类推断也不充分；户型讲解与关注引导不能独立证明从业身份，建议补账号简介。',
 '1-42':'Qwen把介绍第三方区域公司的文案误作发布者第一人称；理由还出现原输入没有的“我们深耕齐鲁十九载”。',
 '1-47':'Qwen因无机构背书归普通；无身份线索应保留未知，需核验账号。',
 '2-29':'Codex参考的专业类推断偏强，Qwen保留身份不明更稳妥；冻结原判不覆盖。'
}
for row in rows:
 sid=row[0]
 note=('需补账号简介、认证主体或从业服务证据；当前无法确定哪一方正确。' if row[9]=='不一致' else '') if full else postreview.get(sid,'需补账号简介、认证主体或从业服务证据；当前无法确定哪一方正确。' if row[9]=='不一致' else '')
 if full:
  notes={'1-11':'预约看房属于服务线索；错别字、口语化不能证明普通账号。','1-21':'仅据项目名和人名推断销售身份，证据不足。','1-36':'Qwen承认无认证和第一人称承接证据，却仍判官方，需核验账号。','1-42':'报道第三方公司活动不等于发布账号官方身份；第三人称文案被误当第一人称。','2-02':'Qwen用“隐含第一人称”和项目名推断官方，需核验账号。','2-32':'项目名加个人姓名不足以确认销售身份。','2-35':'项目名加个人姓名不足以确认销售身份。','2-40':'Qwen明确称无正文证据，仍推断置业顾问身份。'}
  note=notes.get(sid,note)
 row.append(note)
attempts=[json.loads(l) for l in (out/'api_attempts.jsonl').read_text(encoding='utf-8').splitlines()]
cost={'attempts':len(attempts),'prompt_tokens':0,'completion_tokens':0,'cached_tokens':0,'known_estimated_yuan':0,'unknown_usage_attempts':0,'unknown_cost_attempts':0,'request_seconds':sum(a['seconds'] for a in attempts),'wall_seconds':load('qwen_run.json')['wall_seconds']+(0 if full else load('qwen_run_initial.json')['wall_seconds'])}
for a in attempts:
 u=a.get('usage')
 if not u or 'prompt_tokens' not in u or 'completion_tokens' not in u:cost['unknown_usage_attempts']+=1;continue
 pt=u['prompt_tokens'];ct=u['completion_tokens'];cached=min(pt,u.get('prompt_tokens_details',{}).get('cached_tokens',0))
 cost['prompt_tokens']+=pt;cost['completion_tokens']+=ct;cost['cached_tokens']+=cached
 if pt<=32768:cost['known_estimated_yuan']+=((pt-cached)*.2+cached*.04+ct*.8)/1e6
 else:cost['unknown_cost_attempts']+=1
stats=[]
for dataset in ['专题一','专题二','合计']:
 rr=[r for r in rows if dataset=='合计' or r[1]==dataset];agree=sum(r[9]=='一致' for r in rr)
 stats.append({'dataset':dataset,'n':len(rr),'agree':agree,'agreement':agree/len(rr),'codex_roles':dict(Counter(r[7] for r in rr)),'qwen_roles':dict(Counter(r[8] for r in rr)),'review_count':sum(r[15]=='是' for r in rr),'evidence_pass':sum(r[14]=='通过' for r in rr)})
d={'headers':['样本号','数据集','平台','数据库行ID','文章ID','作者名字','文章标题','Codex发布者角色','Qwen发布者角色','对照结果','Codex理由','Qwen理由','Codex证据','Qwen证据','Qwen证据校验','建议复核','文章链接','输入截取字段','人工确认角色','人工反馈','差异复核意见'], 'rows':rows,'packets':p,'raw':list(raw.values()),'manifest':load('manifest.json'),'run':load('qwen_run.json'),'cost':cost,'stats':stats,'diffs':diffs}
if full:
 oldref={r['sample_id']:r for r in json.loads((base/'codex_reference.json').read_text(encoding='utf-8'))}
 oldq={r['sample_id']:r for r in json.loads((base/'qwen_results_normalized.json').read_text(encoding='utf-8'))}
 d['retest']={'old_agree':sum(oldq[s]['response']['role']==oldref[s]['role'] for s in ref),'new_agree_fixed_old_reference':sum(qs[s]['response']['role']==oldref[s]['role'] for s in ref),'new_agree_revised_reference':sum(qs[s]['response']['role']==ref[s]['role'] for s in ref),'reference_corrections':freeze['prior_reference_label_corrections'],'qwen_changed':[{'sample_id':s,'old':oldq[s]['response']['role'],'new':qs[s]['response']['role']} for s in ref if oldq[s]['response']['role']!=qs[s]['response']['role']]}
(out/'comparison_data.json').write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
if full:print(json.dumps(d['retest'],ensure_ascii=False,indent=2))
print(json.dumps({'stats':stats,'cost':cost,'diffs':diffs},ensure_ascii=False,indent=2))
