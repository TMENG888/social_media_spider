"""Parallel D refinements on frozen units; baseline labels and metadata immutable.

E: local blind review. F: catalogue evidence + necessary attributes.
G: E/F agreement, with adversarial arbitration of disagreement. These are
experimental label supplements only, not promoted production defaults.
"""
import argparse,copy,json,os,re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import delivery_v76 as original
import delivery_v11 as pipeline
from bounded_visible_contract_v60 import review
from comment_identity_protocol_v59 import obj,TEXT
from experiment_routes_v78 import definitions,CONF
from compare_mapreduce_v76 import stats,EXTRA
from evaluate_independent_label_anchors_v59 import evaluate
from evaluate_routes_v78 import EXTRA as EXTRA2,evaluate_projects

VERSION='D-refinement-v80.1-20261010'
LOCAL_SYSTEM='''独立审核一个标签，只看当前切片，不借其他切片、其他项目/房源的属性。
按完整字典路径和说明判定，有相关词不等于满足定义。营销名不证明物业形态或设备。
先说明实际对象和实际事实。价格标签要有本房源对应装修交付状态；总价不自动是精装或毛坯。
科技住宅泛称不证明具体科技系统，平墅不证明别墅。不做常识补全。
评论按本人原话与发言者判断，不能把不同回复人的事实合在同一个人上。
支持则引用当前切片连续逐字证据，不支持允许空引文；不因请求打标签而倾向支持。'''
LOCAL_SCHEMA=obj({'supported':{'type':'boolean'},'actual_object':TEXT,'actual_fact':TEXT,
 'quote':{'type':'string'},'why':TEXT,'confidence':CONF})
KEYS={'type':'array','items':{'type':'string'}}
FACT_SCHEMA=obj({'supported':{'type':'boolean'},'actual_object':TEXT,'actual_fact':TEXT,
 'object_keys':KEYS,'property_keys':KEYS,'qualifier_keys':KEYS,
 'object_matches':{'type':'boolean'},'property_matches':{'type':'boolean'},
 'same_object':{'type':'boolean'},'modality_preserved':{'type':'boolean'},
 'no_inference':{'type':'boolean'},'necessary_attribute_present':{'type':'boolean'},'why':TEXT,'confidence':CONF})
FACT_SYSTEM='''审核一个标签是否被当前切片真实支持。字典不能改写或扩展含义。
只从给定source_catalog选择真实证据键。全文仅确认指代身份，不能借片外属性、装修状态、态度。
object_keys是对象证据，property_keys是本对象具体事实，qualifier_keys是必要限定属性证据。
必要属性按necessary_attribute执行，明确缺失即拒绝；不得拿别的房源精装状态证明本房源精装价格。
同一切片含多个对象也不能互借属性。营销词、项目定位、常识不证明实际配置、形态或交付。
价格、面积、层数、数量必须区分测量对象、单位、口径及预计/承诺/业主反映等模态。
评论保持整条，但各发言者的需求和态度不能混为同一个人的。返回单个最终审核结论。
相关不是支持。不支持是合法结果，不默认高置信度。'''
ARBITER_SYSTEM=FACT_SYSTEM+'''
另有两份独立审核意见，它们都可能出错。重点寻找支持意见遗漏的必要证据或反例。
以原文和字典为准，不按票数、旧标签、意见置信度裁决。无充分证据就拒绝。'''

def catalogue(text):
 out=[]
 # Evidence address catalogue, not a slicing plan: final boundaries never change.
 for m in re.finditer(r'[^。！？\n]+[。！？\n]*|[。！？\n]+',text):
  out.append({'source_key':f'S{len(out)+1:03d}','start':m.start(),'end':m.end(),'text':m.group()})
 return out

def necessary(tag):
 tid=tag['tag_id']
 if tid in ('VOC-0480','VOC-0481'):return '本房源明确毛坯交付或毛坯报价口径；其他房源状态无效'
 if tid in ('VOC-0482','VOC-0483'):return '本房源明确精装/豪装/带装修交付或报价口径；其他房源状态无效'
 if tid=='VOC-0232':return '必须具体说明住宅精装科技系统配置；单独科技住宅四字无效'
 if tid=='VOC-0168':return '明确实际别墅类型或建筑形态；平墅等营销称谓单独无效'
 return '完整标签定义要求的对象和具体属性；不能用近似对象、泛词或其他对象证据补全'

def gate(tag,text,raw,catalog):
 errors=[]
 if not raw or not raw.get('supported'):return False,['模型不支持或未返回']
 if raw['confidence']<.9:errors.append('置信度不足0.90')
 for k in ('object_matches','property_matches','same_object','modality_preserved','no_inference','necessary_attribute_present'):
  if not raw[k]:errors.append('必要检查未通过：'+k)
 by={x['source_key']:x['text'] for x in catalog}
 for k in ('object_keys','property_keys'):
  if not raw[k] or any(x not in by for x in raw[k]):errors.append('证据键缺失或无效：'+k)
 if any(x not in by for x in raw['qualifier_keys']):errors.append('限定证据键无效')
 q=''.join(by.get(x,'') for x in raw['qualifier_keys'])
 tid=tag['tag_id']
 patterns={'VOC-0480':r'毛坯','VOC-0481':r'毛坯','VOC-0482':r'精装|豪装|带装修','VOC-0483':r'精装|豪装|带装修',
  'VOC-0232':r'恒温|恒湿|恒氧|地源热泵|辐射|智能|科技系统|科技设备','VOC-0168':r'独栋|联排|叠拼|双拼|合院|别墅'}
 if tid in patterns and (not q or not re.search(patterns[tid],q)):errors.append('必要限定证据不足：'+necessary(tag))
 return not errors,errors

def local(result,row,tag,runner):
 text=row.get('原文摘录',row.get('原始摘录'))
 req={'source_text':text,'source_kind':result['document']['kind'],'label_definition':definitions({'D'+tag['tag_id'].split('-')[1]:tag})[0]}
 raw,cc,aa,ee=review(LOCAL_SYSTEM,req,LOCAL_SCHEMA,result['document'],'E当前切片局部盲审-v80',runner)
 ok=bool(raw and not ee and raw['supported'] and raw['confidence']>=.9 and raw['quote'] and raw['quote'] in text)
 return {'accepted':ok,'decision':raw,'calls':cc,'audit':aa,'issues':ee}

def fact(result,row,tag,runner,opinions=None):
 text=row.get('原文摘录',row.get('原始摘录'));cat=catalogue(text)
 req={'source_catalog':cat,'object_identity_context':result['document']['text'],
  'source_kind':result['document']['kind'],'necessary_attribute':necessary(tag),
  'label_definition':definitions({'D'+tag['tag_id'].split('-')[1]:tag})[0]}
 if opinions is not None:req['independent_opinions']=opinions
 raw,cc,aa,ee=review(ARBITER_SYSTEM if opinions is not None else FACT_SYSTEM,req,FACT_SCHEMA,result['document'],
  'G分歧对抗裁决-v80' if opinions is not None else 'F必要证据槽位-v80',runner)
 ok,errors=gate(tag,text,raw,cat) if raw and not ee else (False,[])
 return {'accepted':ok,'decision':raw,'calls':cc,'audit':aa,'issues':ee+errors,'source_catalog':cat}

def run(base,d,taxonomy,runner):
 index=pipeline.p.v.registry(taxonomy,base['document']['topic']);byrow={r['unit_id']:r for r in base['rows']}
 pairs=d['conservative_supplement_audit']
 def one(a):
  row=byrow[a['unit_id']];tag=index[a['choice_key']]
  with ThreadPoolExecutor(max_workers=2) as pool:
   e=pool.submit(local,base,row,tag,runner);f=pool.submit(fact,base,row,tag,runner);e,f=e.result(),f.result()
  if e['accepted']==f['accepted']:
   g=copy.deepcopy(f);g['accepted']=e['accepted'] and f['accepted'];g['calls']=[];g['route_note']='E/F一致；不额外调用'
  else:
   g=fact(base,row,tag,runner,[{'route':k,'decision':v['decision'],'issues':v['issues']} for k,v in [('E',e),('F',f)]])
   g['route_note']='E/F分歧；另作对抗核验'
  return dict(unit_id=a['unit_id'],choice_key=a['choice_key'],D_accepted=a['accepted'],E=e,F=f,G=g)
 with ThreadPoolExecutor(max_workers=10) as pool:audits=list(pool.map(one,pairs))
 variants={}
 for route in 'EFG':
  out=copy.deepcopy(base);rows={r['unit_id']:r for r in out['rows']};traces={t['unit_id']:t for t in out['traces']}
  for audit in audits:
   v=audit[route];out['calls']+=v['calls']
   if route=='G':out['calls']+=audit['E']['calls']+audit['F']['calls']
   if not v['accepted']:continue
   row=rows[audit['unit_id']];tag=index[audit['choice_key']];raw=v['decision']
   row['标签明细'].append(pipeline.p.base.label_json(tag))
   row['打标说明']+='\n'+tag['tag_id']+'｜'+raw['why']
   row['备注']+='；'+route+'实验新增，待人工独立确认：'+tag['tag_id'];row['验收状态']='需人工审核'
   traces[row['unit_id']].setdefault('D优化新增证据',[]).append({'tag_id':tag['tag_id'],'route':route,**v})
  out['D_refinement_audit']=audits;out['experiment_route']=route;variants[route]=out
 return variants

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--baseline',type=Path,required=True);ap.add_argument('--d',type=Path,required=True);ap.add_argument('--output-dir',type=Path,required=True);a=ap.parse_args()
 original.activate();read=lambda f:json.loads(f.read_text(encoding='utf-8'));before=read(a.baseline);d=read(a.d)
 ds={r['document']['record_id']:r for r in d['results']};selected=[r for r in before['results'] if r['document']['record_id'] in ds]
 taxonomy=pipeline.p.base.load_taxonomy(pipeline.p.v.legacy.TAXONOMY)
 runner=pipeline.p.base.ApiRunner(a.output_dir,10,key=os.getenv('YS_LLM_API_KEY'));signature=pipeline.p.base.digest(Path(__file__).read_text(encoding='utf-8'))
 def work(r):
  fn=a.output_dir/'documents'/(pipeline.p.base.digest({'implementation':signature,'source':r,'D':ds[r['document']['record_id']]})+'.json')
  if fn.exists():return read(fn)
  out=run(r,ds[r['document']['record_id']],taxonomy,runner);pipeline.p.base.save_json(fn,out);return out
 outputs=[]
 with ThreadPoolExecutor(max_workers=10) as pool:
  for f in as_completed([pool.submit(work,r) for r in selected]):
   outputs.append(f.result());print(json.dumps({'completed':len(outputs),'planned':len(selected)}),flush=True)
 order={r['document']['record_id']:i for i,r in enumerate(selected)}
 ref=read(Path(__file__).with_name('independent_label_anchors_v59.json'));ref['anchors']+=EXTRA
 extra={'reference_type':'独立有限锚点，非人工全量金标准','anchors':EXTRA2}
 reports={};base=dict(before,results=selected)
 for k,v in [('baseline',base),('D',d)]:reports[k]={'counts':stats(v),'reference':evaluate(v,ref),'extra':evaluate(v,extra),'projects':evaluate_projects(v)}
 for route in 'EFG':
  results=sorted([o[route] for o in outputs],key=lambda r:order[r['document']['record_id']]);folder=a.output_dir/route
  data=pipeline.p.base.export(folder,results,before['sampling'],taxonomy,before['business'],runner,'api',True)
  data['summary'].update(version='delivery-v76.4-D-refinement-v80-'+route,planned_articles=8,
   note='D基础上的针对性补标审核实验；保留原MapReduce标签/项目/边界/文案；不是正式准确率或全量覆盖。')
  data['execution_manifest']={'requested_record_ids':list(order),'scope':'针对性子集','seed':None}
  pipeline.p.base.save_json(folder/'delivery_results.json',data)
  reports[route]={'counts':stats(data),'reference':evaluate(data,ref),'extra':evaluate(data,extra),'projects':evaluate_projects(data),
   'tested':sum(len(r['D_refinement_audit']) for r in results),'accepted':sum(v[route]['accepted'] for r in results for v in r['D_refinement_audit']),
   'protocol_errors':sum(bool(v[route]['audit'] and v[route]['audit'][-1]['protocol_issues']) for r in results for v in r['D_refinement_audit'])}
 reports['new_calls']=runner.calls;reports['version']=VERSION;reports['default_changed']=False
 pipeline.p.base.save_json(a.output_dir/'comparison.json',reports)
 for k,v in reports.items():
  if isinstance(v,dict) and 'reference' in v:print(json.dumps({'route':k,'counts':v['counts'],'old_hit':v['reference']['hit_required_tags'],'extra_hit':v['extra']['hit_required_tags']},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
