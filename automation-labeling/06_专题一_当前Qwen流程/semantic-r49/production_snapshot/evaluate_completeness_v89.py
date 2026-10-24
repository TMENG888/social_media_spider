"""Read-only, source-grounded regression measures; not a gold accuracy score."""
import argparse,json,copy
from pathlib import Path
import completeness_v89 as v
def evaluate(prior,current):
 old={r['document']['record_id']:r for r in prior['results']};now={r['document']['record_id']:r for r in current['results']}
 assert set(old)==set(now),'Source batch changed'
 errors=[];count=0;reviewed=0;changes=[]
 tax=v.base.load_taxonomy(v.old.earlier.support.previous.p.p.v.legacy.TAXONOMY)
 indexes={topic:v.old.earlier.support.previous.p.p.v.registry(tax,topic) for topic in [v.base.T1,v.base.T2]}
 for rid,r in now.items():
  d=r['document'];assert d['text']==old[rid]['document']['text']
  index=indexes[d['topic']]
  for row,t in zip(r['rows'],r['traces']):
   count+=1;prose=row.get('具体产品做法',row.get('观点摘要'));quote=row.get('原文摘录',row.get('原始摘录'))
   assert quote==d['text'][t['起点']:t['终点']]
   assert row['标签明细'] and row['打标说明'] and prose
   for tag in row['标签明细']:
    key='D'+tag['标签路径ID'][4:];assert key in index and tag==v.label_json(index[key])
    assert tag['标签路径ID'] in row['打标说明']
   if '本轮字段修复' in t:
    reviewed+=1
    if d['topic']==v.base.T2:assert len(prose)<=80
    for proof in t['标签证据与归属']:
     for span in proof['attribute_spans']:assert d['text'][span['start']:span['end']]==span['quote'] and t['起点']<=span['start']<span['end']<=t['终点']
   if d['kind']=='评论':assert quote==d['text'] and row['映射文章id']==d['row']['文章id']
   for h in ['热度指数','互动深度指数']:assert row[h]==v.numeric_score(d['parent'].get(h))
  changes+=r.get('repair_changes',[])
 def has(rid,tag):return any(tag==t['标签路径ID'] for u in now[rid]['rows'] for t in u['标签明细'])
 anchors=[{'检查':'安澜品牌标签不被产品范围误删','通过':all(has('T2-1263114957749348749',x) for x in ['VOC-0094','VOC-0095','VOC-0107'])},
  {'检查':'安澜区位地铁补标','通过':has('T2-1263114957749348749','VOC-0142')},
  {'检查':'保利建筑面积保留','通过':has('T1-8000912876517501943','VOC-0186')},
  {'检查':'香港实用面积不硬改建筑面积','通过':not has('T1-8000912876517501741','VOC-0186')},
  {'检查':'香港5套房不当5主卧','通过':not has('T1-8000912876517501741','VOC-0210')},
  {'检查':'香港外立面石灰岩保留','通过':has('T1-8000912876517501741','VOC-0416')}]
 pending=[{'record_id':r['document']['record_id'],'unit_id':q['unit_id'],'reason':q['原因'],'in_main':any(u['unit_id']==q['unit_id'] for u in r['rows'])} for r in current['results'] for q in r.get('pending_units',[])]
 baseline_units={u['unit_id']:u for r in prior['results'] for u in r['rows']}
 main={u['unit_id']:u for r in current['results'] for u in r['rows']}
 was_empty={uid for uid,u in baseline_units.items() if not u['标签明细'] or not u['打标说明'] or not u.get('具体产品做法',u.get('观点摘要'))}
 repaired=was_empty&set(main)
 newly_excluded={e.get('原单元ID') for r in current['results'] for e in r.get('excluded_intervals',[])}-{e.get('原单元ID') for r in prior['results'] for e in r.get('excluded_intervals',[])}
 report={'passed_contract':True,'source_batch_unchanged':True,'baseline':v.metrics(prior['results']),'new':v.metrics(current['results']),
  'machine_repaired_units':reviewed,'initial_incomplete_units':len(was_empty),'initial_incomplete_now_in_main':len(repaired),
  'initial_incomplete_newly_excluded':len(was_empty&newly_excluded),'initial_incomplete_pending_only':len(was_empty-set(main)-newly_excluded),
  'main_and_pending_overlap':sum(x['in_main'] for x in pending),'anchors':anchors,'changes':changes,'pending':pending,
  'limitations':'主表非空率不等于标签召回率或精确率；正常历史单元未全量重审；没有人工金标准。不确定记录仍保留，源缺失元数据不编造。'}
 return report
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--input',type=Path,required=True);ap.add_argument('--prior',type=Path,default=v.DEFAULT_PRIOR);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
 report=evaluate(json.loads(a.prior.read_text(encoding='utf-8')),json.loads(a.input.read_text(encoding='utf-8')));v.save_json(a.output,report)
 print(json.dumps({k:x for k,x in report.items() if k not in ['changes','pending']},ensure_ascii=False))
