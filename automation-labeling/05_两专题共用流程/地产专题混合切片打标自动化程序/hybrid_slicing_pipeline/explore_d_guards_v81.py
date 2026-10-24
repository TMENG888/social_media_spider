"""H/I selective necessary-evidence guards on D additions, no re-selection.

H deterministic necessary attributes plus sales-source review.
I same guards plus independent semantic review for risky label types only.
Never changes inherited original labels, projects, prose or slicing boundaries.
"""
import argparse,copy,json,os,re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import delivery_v76 as original
import delivery_v11 as p
from bounded_visible_contract_v60 import review
from comment_identity_protocol_v59 import obj,TEXT
from experiment_routes_v78 import definitions,CONF
from explore_d_v80 import catalogue
from compare_mapreduce_v76 import stats,EXTRA
from evaluate_independent_label_anchors_v59 import evaluate
from evaluate_routes_v78 import EXTRA as EXTRA2,evaluate_projects

RISKY={'VOC-0168','VOC-0232','VOC-0184','VOC-0186','VOC-0480','VOC-0481','VOC-0482','VOC-0483','VOC-0492'}
PATTERNS={'VOC-0168':r'排屋|独栋|联排|叠拼|双拼|合院|别墅',
 'VOC-0232':r'恒温|恒湿|恒氧|地源热泵|辐射|智能|科技系统|科技设备',
 'VOC-0184':r'(?:面宽|开间|宽度)[^，。；！\n]{0,12}?\d+(?:\.\d+)?\s*(?:米|m|厘米|cm)',
 'VOC-0186':r'\d+(?:\.\d+)?\s*(?:㎡|m²|m2|平方米|平米|平方|平)',
 'VOC-0480':r'毛坯','VOC-0481':r'毛坯','VOC-0482':r'精装|豪装|带装修','VOC-0483':r'精装|豪装|带装修'}
REASONS={'VOC-0168':'缺少明确实际别墅形态，营销称谓不能确认',
 'VOC-0232':'缺少具体科技系统配置，泛称科技住宅不能确认',
 'VOC-0184':'缺少面宽的具体尺寸和单位，不能把四面宽当尺寸',
 'VOC-0186':'缺少明确面积数值单位，户型称谓不能自动补㎡',
 'VOC-0480':'缺少本房源毛坯口径','VOC-0481':'缺少本房源毛坯口径',
 'VOC-0482':'缺少本房源精装口径','VOC-0483':'缺少本房源精装口径'}
SCHEMA=obj({'supported':{'type':'boolean'},'source_purpose':{'type':'string','enum':['房源销售推介','销售咨询或承诺经历','产品分析介绍','其他或不明']},
 'same_object':{'type':'boolean'},'quote':{'type':'string'},'necessary_quote':{'type':'string'},'why':TEXT,'confidence':CONF})
SYSTEM='''独立审核指定标签，严格按字典定义，不因旧模型已选择而默认支持。
当前切片为属性证据范围；全文只确认对象身份及来源性质，不能借其他房源的属性。
尤其区分：产品比较分析对设备的介绍，不是客户销售承诺经历；明确房源销售推介可以记录该房源装标口径，但不证明实际兑现。
科技住宅不是具体科技系统；平墅不是实际别墅；四面宽不等于明确宽度尺寸；230户型不能自动补平方米。
装修价格必须同一房源同时明确装修状态和价格，不能引用其他房源的精装/豪装描述。
source_purpose按全文判断，不默认是销售。quote和necessary_quote支持时均逐字引用当前切片，不支持允许空。
源文的预计、业主反映、销售报价等口径必须保留；没有足够证据拒绝是合法结论。'''

def hard_check(tag,text):
 tid=tag['tag_id']
 if tid in PATTERNS and not re.search(PATTERNS[tid],text,re.I):return False,REASONS[tid]
 return True,''

def semantic(base,row,tag,runner,route):
 text=row.get('原文摘录',row.get('原始摘录'))
 req={'source_text':text,'source_purpose_context':base['document']['text'],
  'label_definition':definitions({'D'+tag['tag_id'].split('-')[1]:tag})[0]}
 raw,cc,aa,ee=review(SYSTEM,req,SCHEMA,base['document'],route+'高风险必要属性审核-v81',runner)
 # A single sufficient quote may carry both fact and required attribute; do
 # not demand the model duplicate it in two fields. Both remain source-owned.
 q=(raw['necessary_quote'] or raw['quote']) if raw else ''
 ok=bool(raw and not ee and raw['supported'] and raw['same_object'] and raw['confidence']>=.9 and raw['quote']
  and raw['quote'] in text and q and q in text)
 if tag['tag_id']=='VOC-0492' and raw and raw['source_purpose'] not in ('房源销售推介','销售咨询或承诺经历'):ok=False;ee+=['来源不是明确销售推介或承诺经历']
 return {'accepted':ok,'decision':raw,'calls':cc,'audit':aa,'issues':ee}

def run(base,d,taxonomy,runner):
 index=p.p.v.registry(taxonomy,base['document']['topic']);rows={r['unit_id']:r for r in base['rows']}
 adds=[a for a in d['conservative_supplement_audit'] if a['accepted']]
 def one(a):
  row=rows[a['unit_id']];tag=index[a['choice_key']];text=row.get('原文摘录',row.get('原始摘录'));ok,why=hard_check(tag,text)
  fixed={'accepted':ok,'decision':{'why':why or '必要词面门槛通过；不单独证明语义正确'},'calls':[],'audit':[],'issues':[why] if why else []}
  if not ok:return dict(unit_id=a['unit_id'],choice_key=a['choice_key'],H=copy.deepcopy(fixed),I=copy.deepcopy(fixed))
  if tag['tag_id'] not in RISKY:return dict(unit_id=a['unit_id'],choice_key=a['choice_key'],H=copy.deepcopy(fixed),I=copy.deepcopy(fixed))
  if tag['tag_id']=='VOC-0492':
   with ThreadPoolExecutor(max_workers=2) as pool:
    h=pool.submit(semantic,base,row,tag,runner,'H');i=pool.submit(semantic,base,row,tag,runner,'I');h,i=h.result(),i.result()
  else:h=copy.deepcopy(fixed);i=semantic(base,row,tag,runner,'I')
  return dict(unit_id=a['unit_id'],choice_key=a['choice_key'],H=h,I=i)
 with ThreadPoolExecutor(max_workers=10) as pool:audits=list(pool.map(one,adds))
 outputs={}
 for route in 'HI':
  out=copy.deepcopy(base);rr={r['unit_id']:r for r in out['rows']};traces={t['unit_id']:t for t in out['traces']};drows={r['unit_id']:r for r in d['rows']}
  for a in audits:
   v=a[route];out['calls']+=v['calls'];row=rr[a['unit_id']];tag=index[a['choice_key']]
   if v['accepted']:
    row['标签明细'].append(p.p.base.label_json(tag))
    old=next(x for x in d['conservative_supplement_audit'] if x['unit_id']==a['unit_id'] and x['choice_key']==a['choice_key'])
    row['打标说明']+='\n'+tag['tag_id']+'｜'+(v['decision'].get('why') if v['audit'] else old['decision']['why'])
    row['备注']+='；'+route+'选择性审核新增，待人工确认：'+tag['tag_id']
   else:row['备注']+='；新增候选暂不确认'+tag['tag_id']+'：'+('；'.join(v['issues']) or (v['decision'] or {}).get('why','模型审核未通过'))
   row['验收状态']='需人工审核'
   traces[row['unit_id']].setdefault('D选择性审核证据',[]).append({'tag_id':tag['tag_id'],**v})
  out['D_selective_audit']=audits;outputs[route]=out
 return outputs

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--baseline',type=Path,required=True);ap.add_argument('--d',type=Path,required=True);ap.add_argument('--output-dir',type=Path,required=True);a=ap.parse_args()
 original.activate();read=lambda f:json.loads(f.read_text(encoding='utf-8'));before=read(a.baseline);d=read(a.d);ds={r['document']['record_id']:r for r in d['results']}
 selected=[r for r in before['results'] if r['document']['record_id'] in ds];taxonomy=p.p.base.load_taxonomy(p.p.v.legacy.TAXONOMY)
 runner=p.p.base.ApiRunner(a.output_dir,10,key=os.getenv('YS_LLM_API_KEY'));signature=p.p.base.digest(Path(__file__).read_text(encoding='utf-8'))
 def work(r):
  fn=a.output_dir/'documents'/(p.p.base.digest({'implementation':signature,'source':r,'D':ds[r['document']['record_id']]})+'.json')
  if fn.exists():return read(fn)
  out=run(r,ds[r['document']['record_id']],taxonomy,runner);p.p.base.save_json(fn,out);return out
 outputs=[]
 with ThreadPoolExecutor(max_workers=10) as pool:
  for f in as_completed([pool.submit(work,r) for r in selected]):outputs.append(f.result());print(json.dumps({'completed':len(outputs),'planned':len(selected)}),flush=True)
 order={r['document']['record_id']:i for i,r in enumerate(selected)};ref=read(Path(__file__).with_name('independent_label_anchors_v59.json'));ref['anchors']+=EXTRA
 reports={};extra={'reference_type':'独立有限参考','anchors':EXTRA2}
 for route in 'HI':
  results=sorted([o[route] for o in outputs],key=lambda r:order[r['document']['record_id']]);folder=a.output_dir/route
  data=p.p.base.export(folder,results,before['sampling'],taxonomy,before['business'],runner,'api',True)
  data['summary'].update(version='delivery-v76.4-D-selective-v81-'+route,planned_articles=8,note='D选择性必要证据实验；不修改原标签/项目/边界；非人工准确率。')
  data['execution_manifest']={'requested_record_ids':list(order),'scope':'针对性子集','seed':None};p.p.base.save_json(folder/'delivery_results.json',data)
  reports[route]={'counts':stats(data),'reference':evaluate(data,ref),'extra':evaluate(data,extra),'projects':evaluate_projects(data),
   'accepted':sum(x[route]['accepted'] for r in results for x in r['D_selective_audit'])}
 reports['new_calls']=runner.calls;reports['default_changed']=False;p.p.base.save_json(a.output_dir/'comparison.json',reports)
 for k in 'HI':print(json.dumps({'route':k,'accepted':reports[k]['accepted'],'counts':reports[k]['counts']},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
