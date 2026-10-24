"""Targeted loss guard after field repair; old labels remain candidates only."""
import argparse,copy,json,os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import completeness_v89 as v
from bounded_visible_contract_v60 import review
from comment_identity_protocol_v59 import obj,TEXT
from experiment_routes_v78 import CONF,definitions
SYSTEM='''检查旧版消失标签是否真的有据。只有lost_candidates是待判标签，不要照抄旧版结论。
每个unit的每个候选逐一返回。看完整source_text理解对象，属性证据必须在当前unit.text，不借其他项目/户型数值。
标签定义是唯一标准，不添加门槛。专题一产品；专题二允许品牌、土地/交通、产品、交付、客户/服务等适用分支。
上市、信用评级、物业能力都是专题二品牌事实，不因无户型而拒绝；集团事实对象仍为集团，不称项目独有。
实用面积不是建筑面积，5套房不是5主卧，花园天台不是阳台。泛称会所高定/高标准不证明具体整体风格或空间尺度。
石材科普及景墙材质不能当外立面材质；普通连廊不证明防风雨功能。不能把宣传产品当客户自述需求。
属性quotes为unit内逐字短引文，多个引文分开放；对象context_quotes是全文逐字引文。不要拼省略号，不用推测替代证据。
support=true只在定义、对象、事实和模态均真实匹配；false说清缺哪个必要属性。证据格式问题不代表事实不存在。
rewrite是20-80字忠实摘要或转写产品做法。与本片已有通过文案一样可保留，不用强行塞所有标签数值，不加无据效果。
项目绑定只据全文明示项目或评论父文身份，父文不补评论标签、评价。未知归属不硬填。
每条标签理由讲清对象和证据为何匹配。不输出过程。只返回合同JSON。'''
def schema():
 verdict=obj({'key':TEXT,'support':{'type':'boolean'},'quotes':v.STRINGS,'context_quotes':v.STRINGS,'object':TEXT,'reason':TEXT,'confidence':CONF})
 unit=obj({'unit_id':TEXT,'labels':{'type':'array','items':verdict},'rewrite':TEXT,'confidence':CONF,
  'project_refs':{'type':'array','items':obj({'project_id':TEXT,'context_source':{'type':'string','enum':['source','parent']},'quote':TEXT})}})
 return obj({'units':{'type':'array','items':unit}})
def lost_items(prior,result):
 current={u['unit_id']:u for u in result['rows']};excluded={e.get('原单元ID') for e in result.get('excluded_intervals',[])};items=[]
 for row,t in zip(prior['rows'],prior['traces']):
  if row['unit_id'] in excluded:continue
  existing={x['标签路径ID'] for x in current.get(row['unit_id'],{}).get('标签明细',[])}
  lost=[x for x in row['标签明细'] if x['标签路径ID'] not in existing]
  if not lost:continue
  proofs=t.get('标签证据与理由',t.get('标签证据与归属',[]));proofs={x.get('choice_key',x.get('key')):x for x in proofs}
  items.append({'unit_id':row['unit_id'],'start':t['起点'],'end':t['终点'],'text':row.get('原文摘录',row.get('原始摘录')),
   'existing_rewrite':current.get(row['unit_id'],{}).get('具体产品做法',current.get(row['unit_id'],{}).get('观点摘要')),
   'lost_candidates':[{'key':'D'+x['标签路径ID'][4:],'old_evidence':proofs.get('D'+x['标签路径ID'][4:],{})} for x in lost]})
 return items
def process(prior,result,index,business,runner,out):
 result=copy.deepcopy(result);items=lost_items(prior,result);doc=result['document'];calls=[];audits=[];decisions=[]
 original={u['unit_id']:(u,t) for u,t in zip(prior['rows'],prior['traces'])};current={u['unit_id']:(u,t) for u,t in zip(result['rows'],result['traces'])}
 for start in range(0,len(items),3):
  subset=items[start:start+3];keys={c['key'] for u in subset for c in u['lost_candidates']};allowed={k:index[k] for k in keys if k in index}
  req={'source_text':doc['text'],'source_type':doc['kind'],'research_topic':doc['topic'],'units':subset,'definitions':definitions(allowed),
   'business_projects':business['projects'],'parent_identity_context':v.base.choose_source(doc['parent'])[1] if doc['kind']=='评论' else ''}
  raw,cc,aa,err=review(SYSTEM,req,schema(),doc,'紧凑旧标签丢失保护-v89',runner);calls+=cc;audits+=aa
  if raw is None:
   decisions.append({'来源':doc['record_id'],'未完成':'旧标签丢失保护API/结构失败'});continue
  v.normalize_keys(raw,index);by={u['unit_id']:u for u in raw['units']};wanted={u['unit_id']:u for u in subset}
  for uid,item in wanted.items():
   u=by.get(uid)
   if not u:continue
   verdicts={t['key']:t for t in u['labels']};wantedkeys={t['key'] for t in item['lost_candidates']}
   if not wantedkeys.issubset(verdicts):decisions.append({'unit_id':uid,'未完成':'丢失候选未全部返回'});continue
   accepted=[]
   for key in wantedkeys:
    t=verdicts[key];decisions.append({'unit_id':uid,**t})
    if key not in index or not t['support'] or t['confidence']<.9:continue
    # Never fix interpretation here; normalize only literal formatting.
    temp={'units':[{'unit_id':uid,'labels':[t]}]};v.restore_format_quotes(temp,doc,[item],audits)
    if not t['quotes'] or not all(v.literal(q,item['text']) for q in t['quotes']) or not all(v.literal(q,doc['text']) for q in t['context_quotes']):continue
    accepted.append(t)
   if not accepted:continue
   if uid in current:
    row,trace=current[uid]
    for t in accepted:
     tag=v.label_json(index[t['key']])
     if tag not in row['标签明细']:
      row['标签明细'].append(tag);row['打标说明']+='\n'+tag['标签路径ID']+'｜对象='+t['object']+'｜证据：'+'；'.join(t['quotes'])+'｜理由：'+t['reason']
    trace['旧标签丢失保护确认']=accepted
    row['备注']+='；消失旧标签已按原证据和真实定义定向核验后恢复，不是直接复制'
   else:
    oldrow,oldt=original[uid];prose=u['rewrite']
    if not prose or (doc['topic']==v.base.T2 and len(prose)>80) or (len(item['text'])>40 and prose==item['text']):continue
    pending=next((q for q in result.get('pending_units',[]) if q['unit_id']==uid),{})
    draft=pending.get('补全候选') or {}
    data={'unit_id':uid,'decision':'supported','labels':accepted,'rewrite':prose,'confidence':u['confidence'],
     'identity':draft.get('identity') or {'brand':None,'entity':None,'project_name':None,'city':None,'quotes':[]},
     'project_refs':u['project_refs'],'expressions':draft.get('expressions') or [oldrow.get('表达类型','事实介绍')],
     'emotions':draft.get('emotions') or [oldrow.get('情绪态度','无态度')]}
    template=dict(result,rows=[oldrow]);row,trace=v.make_row(template,item,data,index,business)
    row['备注']+='；本片已确认旧标签恢复；其他新候选仍保留待核，未宣称全部标签覆盖完成';trace['旧标签丢失保护确认']=accepted
    current[uid]=(row,trace)
   result.setdefault('repair_changes',[]).append({'unit_id':uid,'处理':'消失旧标签定向确认后恢复','原因':'；'.join(t['key']+'：'+t['reason'] for t in accepted)})
 pairs=sorted(current.values(),key=lambda p:p[1]['起点']);result['rows']=[u for u,t in pairs];result['traces']=[t for u,t in pairs]
 result['calls']+=calls;result['audit']+=audits;result['lost_label_decisions']=decisions
 v.save_json(out/'documents'/(v.digest(doc['record_id'])+'.json'),result);return result
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--input',type=Path,required=True);ap.add_argument('--output-dir',type=Path,required=True);ap.add_argument('--prior',type=Path,default=v.DEFAULT_PRIOR);a=ap.parse_args()
 a.output_dir.mkdir(parents=True,exist_ok=True);p=json.loads(a.input.read_text(encoding='utf-8'));baseline=json.loads(a.prior.read_text(encoding='utf-8'));priors={r['document']['record_id']:r for r in baseline['results']}
 tax=v.base.load_taxonomy(v.old.earlier.support.previous.p.p.v.legacy.TAXONOMY);indexes={topic:v.old.earlier.support.previous.p.p.v.registry(tax,topic) for topic in [v.base.T1,v.base.T2]};runner=v.ApiRunner(a.output_dir,10,key=os.getenv('YS_LLM_API_KEY'))
 signature=v.digest({'code':Path(__file__).read_text(encoding='utf-8'),'tax':tax,'source':v.digest(p['results'])})
 def work(r):
  cp=a.output_dir/'documents'/(v.digest(r['document']['record_id'])+'.json')
  if cp.exists():
   cached=json.loads(cp.read_text(encoding='utf-8'))
   if cached.get('retention_signature')==signature:return cached
  rr=process(priors[r['document']['record_id']],r,indexes[r['document']['topic']],p['business'],runner,a.output_dir);rr['retention_signature']=signature;v.save_json(cp,rr);return rr
 results=[]
 with ThreadPoolExecutor(max_workers=10) as pool:
  for f in as_completed([pool.submit(work,r) for r in p['results']]):
   results.append(f.result())
   if len(results)%30==0:print(json.dumps({'retention_sources':len(results),'metrics':v.metrics(results)},ensure_ascii=False),flush=True)
 order={r['document']['record_id']:i for i,r in enumerate(p['results'])};results.sort(key=lambda r:order[r['document']['record_id']])
 final=v.base.export(a.output_dir,results,p['sampling'],tax,p['business'],runner,'api',True);final['summary'].update(version=v.VERSION+'-retention',pipeline='MapReduce/H切片＋定向字段补全＋同定义核验＋丢失旧标签原证据保护',note='完整主表与未完成待核同时披露；正常历史单元未全量重审，全部需人工审核；未知身份和缺失源指数不编造。')
 final['delivery_changes']=[c for r in results for c in r.get('repair_changes',[])];final['new_test_status']=dict(p['new_test_status'],new=v.metrics(results),retention_guard_real_api=True)
 final['execution_manifest']=p.get('execution_manifest',{});final['tables']['未完成待核']=[q for r in results for q in r.get('pending_units',[])]
 v.save_json(a.output_dir/'delivery_results.json',final);print(json.dumps(final['new_test_status'],ensure_ascii=False),flush=True)
if __name__=='__main__':main()
