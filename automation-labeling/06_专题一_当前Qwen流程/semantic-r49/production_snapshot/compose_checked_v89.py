"""Compose delivery with explicitly source-checked case QA, not gold accuracy."""
import argparse,copy,json
from pathlib import Path
import completeness_v89 as v
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--input',type=Path,required=True);ap.add_argument('--output-dir',type=Path,required=True);a=ap.parse_args()
 p=json.loads(a.input.read_text(encoding='utf-8'));results=copy.deepcopy(p['results']);byid={r['document']['record_id']:r for r in results};changes=[]
 tax=v.base.load_taxonomy(v.old.earlier.support.previous.p.p.v.legacy.TAXONOMY);tags={t['tag_id']:t for t in tax}
 cases=[('T1-75149-M006','VOC-0332','五进九境','归家礼序未明确说社区大门，不能替代大门风格对象；有意义的空间理念保留待核，不硬凑标签。'),
  ('T1-75303-M010','VOC-0373','高定会所','高定会所没有描述具体整体风格；配置会所和服务活动分开，不能为完整字段硬凑会所风格。'),
  ('T1-75303-M011','VOC-0373','高标准会所','高标准、提前运营及活动次数不是会所具体整体风格；没有泛指会所运营的专题一产品标签，保留待核。'),
  ('T1-75447-M003','VOC-0416','石材','片内有石材甄选和铺装工艺，但没有明确用于外立面；不能将景墙或未限定部位的奢石标为外立面材料。'),
  ('T2-1263114957749348749-V005','VOC-0185','进深0.7米','0.7米修饰阳台，不是整个户型进深；保留尺寸原文，不硬改计量对象。'),
  ('T1-2467985060850735035-M004','VOC-0414','景观连廊','原文只有景观连廊，未说明防风雨/遮雨功能，不可直接标为风雨连廊。')]
 for uid,tid,anchor,reason in cases:
  result=next(r for r in results if r['document']['record_id']==uid.rsplit('-',1)[0]);row=next((u for u in result['rows'] if u['unit_id']==uid),None)
  if not row or not any(t['标签路径ID']==tid for t in row['标签明细']):continue
  pos=next(i for i,u in enumerate(result['rows']) if u['unit_id']==uid);trace=result['traces'][pos];quote=row.get('原文摘录',row.get('原始摘录'));assert anchor in quote
  before=copy.deepcopy(row);removed=[t for t in row['标签明细'] if t['标签路径ID']==tid];row['标签明细']=[t for t in row['标签明细'] if t['标签路径ID']!=tid]
  row['打标说明']='\n'.join(s for s in row['打标说明'].splitlines() if tid not in s);row['备注']+='；本次源文核查：'+reason
  trace['本次案例源文核查']={'移出候选':removed,'原因':reason,'性质':'已知案例核查，不是总体准确率评估'}
  trace['标签证据与归属']=[t for t in trace.get('标签证据与归属',[]) if t.get('key',t.get('choice_key'))!='D'+tid[4:]]
  if not row['标签明细']:
   result['rows'].pop(pos);result['traces'].pop(pos)
  result.setdefault('pending_units',[]).append({'unit_id':uid,'record_id':result['document']['record_id'],'来源类型':result['document']['kind'],
   '原文':quote,'起点':trace['起点'],'终点':trace['终点'],'原因':'源文案例核查：'+reason,'旧单元':before,'补全候选':None,'校验':None})
  result['complete']=False;changes.append({'unit_id':uid,'处理':'源文核查错误细项，保留正确标签/转人工','原因':reason})
 # Brand facts remain corporate facts; the article association is independently
 # clear from this source's title and repeated named project, not search terms.
 anlan=byid['T2-1263114957749348749'];brand=next((u for u in anlan['rows'] if u['unit_id'].endswith('V002')),None)
 if brand:
  assert '1992年在香港联交所上市' in brand['原始摘录'] and '惠誉A-、标普A-' in brand['原始摘录']
  brand['观点摘要']='中海地产1992年在港交所上市，获惠誉A-、标普A-评级；中海物业服务多类机构，并提供颂系一站式生活服务。'
  verified=[('VOC-0094','中海地产','1992年在香港联交所上市','原文明确公司上市地点及年份，符合上市公司定义。'),
   ('VOC-0095','中海地产','国际评级机构给予信用评级分别是惠誉A-、标普A-','原文给出评级机构及信用等级，符合信用评级定义。'),
   ('VOC-0107','中海物业','超1/5世界500强公司指定物业服务商','原文明示服务覆盖机构和物业服务能力，符合物业配套能力定义。')]
  for tid,object_name,quote,why in verified:
   assert quote in brand['原始摘录']
   tag=v.label_json(tags[tid])
   if tag not in brand['标签明细']:
    brand['标签明细'].append(tag);brand['打标说明']+='\n'+tid+'｜对象='+object_name+'｜证据：'+quote+'｜理由：'+why
  project=next(pj for pj in p['business']['projects'] if pj['id']=='C02')
  assert any(alias in anlan['document']['text'][:150] for alias in project['aliases'])
  brand.update(project_id=[project['id']],项目名称=[project['name']],项目角色=[project['role']])
  brand['备注']+='；本文开头明确安澜北京，品牌段作为开发商背景关联C02；标签事实对象仍是中海地产/物业，不称项目独有属性。'
  changes.append({'unit_id':brand['unit_id'],'处理':'补完整品牌摘要及文章研究项目关联','原因':'原文明确上市、评级、物业背景；篇首明确安澜北京，不从检索词猜项目'})
 # Historical exclusions are still in the full audit. The final exclusion
 # table must not count the same source interval twice or mark a re-included
 # or now-pending comment as also currently excluded.
 for r in results:
  remaining=[]
  for q in r.get('pending_units',[]):
   raw=q.get('补全候选');ck=q.get('校验')
   if v.confirmed_no_label(raw,ck) and not any(s in q['原因'] for s in ['API','结构修复','文本长度违反','证据格式异常']):
    r.setdefault('excluded_intervals',[]).append({'原单元ID':q['unit_id'],'起点':q['起点'],'终点':q['终点'],'原文':q['原文'],
     '原因':raw['reason'],'类型':'两轮一致无适用范围','本轮复查':raw,'校验':ck})
    changes.append({'unit_id':q['unit_id'],'处理':'一致无关判定转排除审计','原因':'范围内=false代表范围外，不应当作判定失败；'+raw['reason']})
   else:remaining.append(q)
  r['pending_units']=remaining
  pending={}
  for q in r.get('pending_units',[]):
   k=(q['unit_id'],q['起点'],q['终点'])
   if k in pending:pending[k]['原因']+='；'+q['原因'];r['audit'].append({'原因':'同一待核单元的其他历史候选已合并展示','历史候选':q})
   else:pending[k]=q
  r['pending_units']=list(pending.values())
  superseded={(t['起点'],t['终点']) for t in r['traces']}|{(q['起点'],q['终点']) for q in r['pending_units']}
  exclusions={}
  for e in r.get('excluded_intervals',[]):
   if e.get('起点') is None or e.get('终点') is None:
    quote=e['原文'];body=r['document']['text']
    if quote==body:e.update(起点=0,终点=len(body))
    elif body.count(quote)==1:e.update(起点=body.index(quote),终点=body.index(quote)+len(quote))
   k=(e.get('起点'),e.get('终点'))
   if k in superseded:
    r['audit'].append({'原因':'历史排除本轮已重新纳入主表或待核，不在当前排除数重复计算','历史排除':e});continue
   if k in exclusions:r['audit'].append({'原因':'历史重复排除区间已合并计数','历史排除':exclusions[k]})
   exclusions[k]=e
  r['excluded_intervals']=list(exclusions.values())
  r['complete']=not r['pending_units']
 final=v.base.export(a.output_dir,results,p['sampling'],tax,p['business'],None,'api',True)
 final['summary'].update(version=v.VERSION+'-source-checked',pipeline='MapReduce/H语义边界＋异常字段补全＋定义核验＋旧标签证据保护＋已知案例源文核查',note='主表重要内容字段非空，不代表全部标签准确或全部来源完成；待核及排除原文均保留。全部人工审核，未知身份与源指数不编造。')
 final['delivery_changes']=p['delivery_changes']+changes;final['new_test_status']=dict(p['new_test_status'],new=v.metrics(results),source_checked_cases=changes)
 final['tables']['未完成待核']=[q for r in results for q in r.get('pending_units',[])];final['execution_manifest']=p.get('execution_manifest',{})
 v.save_json(a.output_dir/'delivery_results.json',final);print(json.dumps({'new':v.metrics(results),'source_checked_cases':changes},ensure_ascii=False))
if __name__=='__main__':main()
