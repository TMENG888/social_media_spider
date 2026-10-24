"""Read results, compare frozen references and export a workbook JSON."""
import argparse,copy,json
from pathlib import Path
from verify_delivery_v4 import verify
from verify_dictionary_backfill_v8 import verify as dv
import delivery_v11 as p
from compare_mapreduce_v76 import stats

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--output-dir',type=Path,required=True);a=ap.parse_args();root=Path(__file__).parent
 read=lambda f:json.loads(f.read_text(encoding='utf-8'));ref=read(root/'d_reference_v80.json')
 folders={'D':root/'test_results_v79_1_conservative_supplement',**{k:root/'test_results_v80_1_D_parallel_refinements'/k for k in 'EFG'},**{k:root/'test_results_v81_2_D_selective_guards'/k for k in 'HI'}}
 data={k:read(f/'delivery_results.json') for k,f in folders.items()};d=data['D'];before=read(root/'test_results_v76_4_mapreduce_full/delivery_results.json')
 bases={r['document']['record_id']:r for r in before['results']};dictionary={t['tag_id']:t for t in p.p.base.load_taxonomy(p.p.v.legacy.TAXONOMY)}
 def pairs(v):return {(row['unit_id'],t['标签路径ID']) for r in v['results'] for row in r['rows'] for t in row['标签明细']}
 dp=pairs(d);reports={};comparison=[];changes=[]
 supported={tuple(x) for x in ref['supported']};bad={tuple(x[:2]) for x in ref['unsupported']+ref['insufficient']}
 for k,v in data.items():
  invariants=[];ps=pairs(v);oldpairs=set()
  for r in v['results']:
   base=bases[r['document']['record_id']]
   if r['document']!=base['document'] or len(r['rows'])!=len(base['rows']):invariants.append('源文/边界变化')
   for u,b in zip(r['rows'],base['rows']):
    tags={t['标签路径ID'] for t in u['标签明细']};bt={t['标签路径ID'] for t in b['标签明细']};oldpairs|={(b['unit_id'],t) for t in bt}
    if not bt.issubset(tags):invariants.append('原标签丢失：'+u['unit_id'])
    for f in ['unit_id','content_id','record_id','映射文章id','来源类型','project_id','项目名称','项目角色','项目','品牌组','经营主体','城市','原文摘录','原始摘录','证据定位','证据序号','热度指数','互动深度指数','观点摘要','具体产品做法']:
     if u.get(f)!=b.get(f):invariants.append('原字段改变：'+u['unit_id']+'：'+f)
  reports[k]={'contract':verify(v),'dictionary':dv(v,dictionary),'invariant_errors':invariants,
   'correct_kept':len(ps&supported),'correct_total':35,'bad_kept':len(ps&bad),'bad_total':8,
   'new_vs_D':[list(x) for x in sorted(ps-dp)],'lost_supported':[list(x) for x in sorted(supported-ps)]}
  if reports[k]['contract']['contract_errors'] or reports[k]['dictionary']['errors'] or invariants:raise ValueError('Contract failure '+k)
  s=stats(v);comparison.append({'方案':k,'方法':{'D':'保留D原补标','E':'当前切片局部审核','F':'必要证据槽位核验','G':'双审核共识＋分歧裁决','H':'选择性必要属性闸门','I':'H闸门＋高风险语义核验'}[k],
   '有据新增保留数':len(ps&supported),'有据新增参考总数':35,'问题新增保留数':len(ps&bad),'问题新增参考总数':8,
   '标签关联数':s['tag_associations'],'无标签单元':s['empty_tag_units'],'相较D额外新增':len(ps-dp),
   '原字段及原标签改变数':len(invariants),'缺失文案单元':s['empty_prose_units'],
   '结论':'保留实验底稿' if k=='D' else '继续测试的优先候选，非正式自动验收' if k=='H' else '当前同批结果与H相同，调用更多' if k=='I' else '有据标签损失/新增误标，不采用'})
  for uid,tid in sorted(dp|ps):
   if (uid,tid) in dp and (uid,tid) in ps:continue
   changes.append({'方案':k,'unit_id':uid,'标签路径ID':tid,'相对D变化':'新增' if (uid,tid) in ps else '移出标签明细',
    '独立参考':'有原文依据' if (uid,tid) in supported else '不支持或证据不足' if (uid,tid) in bad else '新增，需另行审核'})
 audit=[]
 for r in d['results']:
  for z in r['conservative_supplement_audit']:
   tid='VOC-'+z['choice_key'][1:];uid=z['unit_id'];pair=(uid,tid)
   row=next(u for u in r['rows'] if u['unit_id']==uid)
   audit.append({'unit_id':uid,'标签路径ID':tid,'标签强调方向':dictionary[tid]['emphasis'],'原文':row.get('原文摘录',row.get('原始摘录')),
    'D确认':z['accepted'],**{k:pair in pairs(data[k]) for k in 'EFGHI'},
    '独立参考':'有据' if pair in supported else '不支持/不足' if pair in bad else '未纳入43项参考，须另审'})
 costs=[]
 for name,folder in [('EFG并行',root/'test_results_v80_1_D_parallel_refinements'),('HI首轮',root/'test_results_v81_1_D_selective_guards'),('HI修正轮',root/'test_results_v81_2_D_selective_guards')]:
  rr=read(folder/'comparison.json');calls=[c for c in rr['new_calls'] if not c.get('cache_hit')]
  costs.append({'阶段':name,'真实新增逻辑请求数':len(calls),'已知总Token':sum(c.get('total_tokens') or 0 for c in calls),
   '已知估算费用元':sum(c.get('estimated_yuan') or 0 for c in calls),'未知usage次数':sum(c.get('unknown_attempt_usage') or 0 for c in calls),
   '口径':'仅本轮API；不包含上轮D候选生成成本；非网关账单。相同请求并发发出也计实际调用，不按request_key去重。'})
 selected=copy.deepcopy(data['H']);tables={'方案对照':comparison,'产品信息单元':selected['tables']['产品信息单元'],'观点信息单元':selected['tables']['观点信息单元'],
  '标签取舍对照':audit,'相对D变化':changes,'本轮费用':costs,'来源追溯':selected['tables']['来源追溯']}
 # Render long source identifiers as text using the original CSV-owned values.
 # Detailed model/call payloads remain in the accompanying result JSON.
 documents={r['document']['record_id']:r['document'] for r in selected['results']}
 compact=[]
 for t in tables['来源追溯']:
  doc=documents[t['record_id']]
  row={k:t.get(k) for k in ['unit_id','record_id','来源类型','平台','主体字段','起点','终点','原文证据']}
  row['源id']=str(doc['row']['id']);row['所属文章ODS主键']=str(doc['parent']['id'])
  row['新标签审核证据']=[{'标签路径ID':x['tag_id'],'通过':x['accepted'],'依据':x.get('decision'),'未通过原因':x.get('issues')} for x in t.get('D选择性审核证据',[])]
  compact.append(row)
 tables['来源追溯']=compact
 schemas={k:selected['schemas'].get(k) or list(v[0]) for k,v in tables.items()}
 selected['tables']=tables;selected['schemas']=schemas;selected['summary']['note']='主表为H选择性审核实验，D保留。35/8为调试样本有限参考，不是准确率；旧项目及文案缺陷未修。'
 a.output_dir.mkdir(parents=True,exist_ok=True);p.p.base.save_json(a.output_dir/'D优化_工作簿源数据.json',selected)
 p.p.base.save_json(a.output_dir/'独立合同及参考评估.json',reports);p.p.base.save_json(a.output_dir/'指标与费用.json',{'comparison':comparison,'costs':costs})
 print(json.dumps({'comparison':comparison,'costs':costs},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
