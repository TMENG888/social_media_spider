"""Deliver stable Hflex rows with non-destructive whole-review suggestions.

Hfull failed national scope; Hscope still withdrew a supported noise tag. Neither
is silently promoted. No extra API calls and no manual gold answers copied as labels.
"""
import argparse,copy,json,re
from pathlib import Path
import delivery_v82 as v

def compose(stable,candidate):
 byid={r['document']['record_id']:r for r in candidate['results']};results=[]
 for base in stable['results']:
  out=copy.deepcopy(base);other=byid[base['document']['record_id']]
  if {r['unit_id'] for r in out['rows']}!={r['unit_id'] for r in other['rows']}:raise ValueError('Candidate scope must preserve stable units')
  cr={row['unit_id']:row for row in other['rows']};ct={trace['unit_id']:trace for trace in other['traces']}
  out['calls']=copy.deepcopy(other['calls'])
  out['final_whole_review']=copy.deepcopy(other.get('final_whole_review'))
  for row,trace in zip(out['rows'],out['traces']):
   proposed=cr[row['unit_id']];check=ct[row['unit_id']].get('最终全标签核验',{})
   ids={tag['标签路径ID'] for tag in row['标签明细']};suggested={tag['标签路径ID'] for tag in proposed['标签明细']}
   changed={key:{'保留主表值':row.get(key),'候选复核值':proposed.get(key)} for key in ['标签明细','project_id','项目名称','项目角色','项目','观点摘要','具体产品做法'] if row.get(key)!=proposed.get(key)}
   notes=['整批尚未完成独立人工金标准验收，需人工审核；末轮建议不自动覆盖主表']
   if ids-suggested:notes.append('末轮建议撤回但尚未确认：'+','.join(sorted(ids-suggested)))
   if suggested-ids:notes.append('末轮建议恢复但尚未确认：'+','.join(sorted(suggested-ids)))
   if any(key in changed for key in ['project_id','项目名称','项目角色','项目']):notes.append('项目身份存在复核分歧：'+check.get('project_reason','见追溯'))
   if check.get('relevance')!='relevant' and check:notes.append('研究范围待核：'+check.get('relevance_reason',''))
   if check.get('prose_verdict')!='supported' and check:notes.append('摘要或做法待核：'+check.get('prose_reason',''))
   if check.get('explanation_verdict')!='supported' and check:notes.append('标签理由待核：'+check.get('explanation_reason',''))
   row['备注']='；'.join(dict.fromkeys(x.strip() for x in re.split('[；;]',row['备注']+'；'+'；'.join(notes)) if x.strip()));row['验收状态']='需人工审核'
   trace['末轮非破坏性审核建议']={'check':check,'变更候选':changed,'处理':'不直接应用；人工确认后修改'}
   trace['校验问题']=list(dict.fromkeys(trace.get('校验问题',[])+notes))
   if changed:out['audit'].append({'原因':'末轮候选变更未应用，等待人工审核','unit_id':row['unit_id'],'变更候选':changed,'语义核验':check})
  results.append(out)
 return results

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--output-dir',type=Path,required=True);a=ap.parse_args();v.core.activate()
 read=lambda route:json.loads((a.output_dir/route/'delivery_results.json').read_text(encoding='utf-8'))
 stable,candidate=read('Hflex'),read('Hscope');results=compose(stable,candidate)
 taxonomy=v.p.p.base.load_taxonomy(v.p.p.v.legacy.TAXONOMY)
 data=v.p.p.base.export(a.output_dir/'Hreview',results,stable['sampling'],taxonomy,stable['business'],None,'api',False)
 data['execution_manifest']=stable['execution_manifest']
 data['summary'].update(version=v.VERSION+'-Hreview',planned_articles=80,smoke_passed=True,batch_complete=all(r['complete'] for r in results),
  mapping_contract='评论映射文章id取评论CSV文章id；父文章ODS主键另存追溯；文章行为空。',
  note='保留Hflex标签与文案；Hscope范围和全标签核验只作非破坏性人工审核建议，不直接应用有争议的撤标签、归属或文案变更。全部单元需人工审核，不作为正式统计。')
 v.p.p.v.expose_unknown_totals(data);v.p.p.base.save_json(a.output_dir/'Hreview/delivery_results.json',data)
 print(json.dumps(data['summary'],ensure_ascii=False),flush=True)

if __name__=='__main__':main()
