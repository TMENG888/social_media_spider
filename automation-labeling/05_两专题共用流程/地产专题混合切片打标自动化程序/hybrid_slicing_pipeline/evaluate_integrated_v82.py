"""Read-only comparison and compact workbook package, retaining full raw audits."""
import argparse,copy,json
from pathlib import Path
from collections import Counter
import delivery_v82 as v

def metrics(data):
 rows=[row for r in data['results'] for row in r['rows']]
 reviews=[check for r in data['results'] for check in r.get('H_review_checks',[])]
 return {'来源数':len(data['results']),'产品单元数':sum(len(r['rows']) for r in data['results'] if r['document']['topic']==v.p.p.base.T1),
  '文章观点数':sum(len(r['rows']) for r in data['results'] if r['document']['topic']==v.p.p.base.T2 and r['document']['kind']=='文章'),
  '评论观点数':sum(len(r['rows']) for r in data['results'] if r['document']['kind']=='评论'),
  '标签总数':sum(len(row['标签明细']) for row in rows),'无标签单元数':sum(not row['标签明细'] for row in rows),
  '待人工审核单元数':sum(row['验收状态']=='需人工审核' for row in rows),
  '产品做法缺失数':sum(not row.get('具体产品做法') for row in rows if '具体产品做法' in row),
  '观点摘要缺失数':sum(not row.get('观点摘要') for row in rows if '观点摘要' in row),
  '复核标签数':len(reviews),'两路复核分歧数':sum(c['context']['verdict']!=c['local']['verdict'] for c in reviews),
  '未路由Map提议数':sum(len(r.get('unrouted_map_proposals',[])) for r in data['results'])}

def anchors_score(data,anchors):
 byid={r['document']['record_id']:r for r in data['results']};details=[]
 for a in anchors:
  r=byid.get(a['record_id'])
  if not r:continue
  quote=a['quote'];start=r['document']['text'].find(quote)
  if start<0:raise ValueError('独立锚点引文不在源文：'+a['record_id'])
  traces={t['unit_id']:t for t in r['traces']}
  rows=[row for row in r['rows'] if traces[row['unit_id']]['起点']<start+len(quote) and traces[row['unit_id']]['终点']>start]
  chosen={t['标签路径ID'] for row in rows for t in row['标签明细']}
  expected=a.get('supported',a.get('support',[]));forbid=a.get('unsupported',a.get('forbid',[]))
  missing=set(expected)-chosen;bad=set(forbid)&chosen
  projects=[row.get('project_id') for row in rows];target=a.get('expected_project')
  wrong=bool(target and (not projects or any(target not in (pid if isinstance(pid,list) else [pid]) for pid in projects)))
  details.append({'record_id':a['record_id'],'原文证据':quote,'应有标签':expected,
   '未直接覆盖标签':sorted(missing),'不应由本事实推导的标签':forbid,'同片警报标签':sorted(bad),'项目归属待核':wrong,
   '实际项目':projects,'预期项目':target,'依据':a.get('why',a.get('reason'))})
 return {'已核验锚点数':len(details),'有据标签应有数':sum(len(x['应有标签']) for x in details),
  '锚点未直接覆盖数':sum(len(x['未直接覆盖标签']) for x in details),'禁推断标签检查数':sum(len(x['不应由本事实推导的标签']) for x in details),
  '禁推断标签同片警报数':sum(len(x['同片警报标签']) for x in details),'项目归属待核锚点数':sum(x['项目归属待核'] for x in details)},details

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--output-dir',type=Path,required=True)
 ap.add_argument('--delivery-route',choices=['Hreview','Hscope','Hfull','Hflex','Hlocal','Hconsensus'],default='Hreview');a=ap.parse_args()
 read=lambda f:json.loads(f.read_text(encoding='utf-8'))
 datasets={'原核心':read(a.output_dir/'core/delivery_results.json')}
 datasets.update({route:read(a.output_dir/route/'delivery_results.json') for route in ['D','Hflex','Hlocal','Hconsensus']})
 if (a.output_dir/'Hfull/delivery_results.json').exists():datasets['Hfull']=read(a.output_dir/'Hfull/delivery_results.json')
 if (a.output_dir/'Hscope/delivery_results.json').exists():datasets['Hscope']=read(a.output_dir/'Hscope/delivery_results.json')
 if (a.output_dir/'Hreview/delivery_results.json').exists():datasets['Hreview']=read(a.output_dir/'Hreview/delivery_results.json')
 smokepath=a.output_dir/'post_smoke_gate.json'
 if smokepath.exists():
  passed=read(smokepath)['passed']
  for route,data in datasets.items():
   if route=='原核心':continue
   data['summary']['smoke_passed']=passed
   data['summary']['batch_complete']=all(r['complete'] for r in data['results'])
   v.p.p.base.save_json(a.output_dir/route/'delivery_results.json',data)
 refpath=a.output_dir/'independent_anchors.json';anchors=read(refpath).get('anchors',[]) if refpath.exists() else []
 reports=[];detail=[]
 for route,data in datasets.items():
  score,checks=anchors_score(data,anchors);reports.append({'方案':route,**metrics(data),**score})
  detail += [dict(x,方案=route) for x in checks]
 selected=copy.deepcopy(datasets[a.delivery_route]);selected['tables']['方案对照']=reports
 selected['tables']['方案验收说明']=[{'方案':'Hfull','结论':'退回，不推荐','原因':'同批终审将专题一全国范围错套北京地域限制；9篇来源受影响，4篇被整篇误排。保留原始失败JSON，不计为纠错改善。'},
  {'方案':'Hscope','结论':'不覆盖主表，只作审核候选','原因':'全国地域误删已修复，但至少误撤一条有据0157噪音标签；仍有大平层错标大高、材料漏标与项目归属问题，不能晋升。'},
  {'方案':'Hreview','结论':'本轮人工审核测试交付','原因':'保留Hflex标签、摘要及做法；将Hscope候选变更和疑点附到备注、追溯与审核队列，不以单次复核投票覆盖原值；所有481单元待人工审核。'},
  {'方案':'Hflex/Hlocal/Hconsensus','结论':'同批对照保留','原因':'共享D上游及两路模型风险核验，不能只凭标签数量判优。句式挑战仅5/7精确符合预期，uncertain作为审核而非直接删标签。'}]
 selected['tables']['独立事实核查']=detail
 challenge=a.output_dir/'synthetic_challenges.json'
 if challenge.exists():selected['tables']['句式边界测试']=[{k:x[k] for k in ['案例','原文','标签路径ID','预期','原硬规则是否通过','模型复核','符合预期','说明']} for x in read(challenge)['cases']]
 corrected=a.output_dir/'synthetic_challenges_neutral.json'
 if corrected.exists():
  selected['tables']['句式边界测试']=[dict(x,提示版本='原提示') for x in selected['tables'].get('句式边界测试',[])]+[dict({k:x[k] for k in ['案例','原文','标签路径ID','预期','原硬规则是否通过','模型复核','符合预期','说明']},提示版本='去除正则否定诱导') for x in read(corrected)['cases']]
 actual=[]
 for name in ['core','postprocess','final_review_calls','challenge_calls']:
  cs=[read(f)['metrics'] for directory in ['calls','call_attempt_history'] for f in (a.output_dir/name/directory).glob('*.json')]
  if cs:actual.append({'阶段':name,'已缓存实际请求数':len(cs),'已知Token':sum(c.get('total_tokens') or 0 for c in cs),
   'Token未知请求数':sum(c.get('total_tokens') is None for c in cs),'已知估算费用元':sum(c['estimated_yuan'] for c in cs if c.get('estimated_yuan') is not None),
   '费用未知请求数':sum(c.get('estimated_yuan') is None for c in cs),
   '说明':'同批多方案共享的上游和复核实际请求只计一次；未知usage不当作真实零成本。'})
 selected['tables']['本轮实验费用']=actual
 selected['summary'].update(folder_all_versions_calls=sum(x['已缓存实际请求数'] for x in actual),
  folder_all_versions_tokens=None if any(x['Token未知请求数'] for x in actual) else sum(x['已知Token'] for x in actual),
  folder_all_versions_estimated_yuan=sum(x['已知估算费用元'] for x in actual),
  folder_all_versions_unknown_price_calls=sum(x['费用未知请求数'] for x in actual))
 selected['summary']['note']+='；无标签比例不是漏标率，独立锚点不是全量人工金标准。同片警报需核对标签实际绑定事实，可能是同片另一个有效事实支持，不能直接算误标。'
 # XLSX cell limits: raw full audits remain in each route/delivery_results.json.
 for table in ['来源追溯','排除及异常']:
  compact=[]
  for row in selected['tables'][table]:
   out={}
   for key,value in row.items():
    if isinstance(value,(dict,list)):
     encoded=json.dumps(value,ensure_ascii=False)
     out[key]=encoded if len(encoded)<=600 else encoded[:450]+'…（审计概要；完整内容见配套'+a.delivery_route+'/delivery_results.json）'
    else:out[key]=value
   if table=='来源追溯':
    out['源文件']='ods_social_media_comment.csv' if row.get('来源类型')=='评论' else 'ods_social_media_post.csv'
    out['标签字典']='置地VOC标签体系_两专题打标版.xlsx'
   compact.append(out)
  selected['tables'][table]=compact
 v.p.p.base.save_json(a.output_dir/'delivery_package.json',selected)
 v.p.p.base.save_json(a.output_dir/'evaluation_report.json',{'comparison':reports,'details':detail,
  'selected_route':a.delivery_route,'note':'策略改变的是标签确认/候选状态，不重切文章。锚点由生成前独立核验提出，仍非完整人工金标准。'})
 print(json.dumps({'comparison':reports,'selected_route':a.delivery_route},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
