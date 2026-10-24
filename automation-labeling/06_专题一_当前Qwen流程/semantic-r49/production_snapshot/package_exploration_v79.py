"""Package existing experiments only; never runs API or changes production defaults."""
import json,copy,argparse
from pathlib import Path
from verify_delivery_v4 import verify
from verify_dictionary_backfill_v8 import verify as dictionary_verify
import delivery_v11 as p

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--output-dir',type=Path,required=True);args=ap.parse_args()
 root=Path(__file__).parent;read=lambda f:json.loads(f.read_text(encoding='utf-8'))
 abc=root/'test_results_v78_1_parallel_routes';dd=root/'test_results_v79_1_conservative_supplement'
 comparison=read(abc/'experiment_comparison.json');dreport=read(dd/'supplement_comparison.json');extra=read(abc/'extra_evaluation.json')
 variants={k:read(abc/k/'delivery_results.json') for k in 'ABC'};variants['D']=read(dd/'delivery_results.json')
 dictionary={t['tag_id']:t for t in p.p.base.load_taxonomy(p.p.v.legacy.TAXONOMY)}
 verification={k:{'contract':verify(v),'dictionary':dictionary_verify(v,dictionary)} for k,v in variants.items()}
 if any(v['contract']['contract_errors'] or v['dictionary']['errors'] for v in verification.values()):raise ValueError('Contract verification failed')
 rows=[]
 for k in ['baseline','A','B','C','D']:
  report=dreport if k=='D' else comparison[k];counts=report['counts'];ref=report['D'] if k=='D' else report['reference']
  rows.append({'方案':k,'方式':{'baseline':'原MapReduce','A':'原提议候选＋全文重核','B':'全字典分支覆盖审核','C':'A/B联合候选＋独立核验','D':'保留原版，仅盲审新增标签'}[k],
   '产品单元':counts['product_units'],'文章观点单元':counts['article_opinion_units'],'评论观点单元':counts['comment_opinion_units'],
   '标签关联数':counts['tag_associations'],'无标签单元':counts['empty_tag_units'],'缺失文案单元':counts['empty_prose_units'],
   '原参考命中':f"{ref['hit_required_tags']}/{ref['processed_required_tags']}",
   '独立追加参考命中':f"{extra[k]['reference']['hit_required_tags']}/11",'追加反例误标数':extra[k]['reference']['forbidden_tag_hits'],
   '项目参考通过':f"{extra[k]['project_hits']}/7",'实验协议问题数':len(report.get('errors',[])) if k!='D' else sum(len(x['issues']) for r in variants[k]['results'] for x in r['conservative_supplement_audit']),
   '采用结论':'原默认保留' if k=='baseline' else '不晋升默认；仅探索对照'})
 costs=[]
 for name,rr in [('ABC共享实验',comparison),('D独立补标盲审',dreport)]:
  calls={x['request_key']:x for x in rr['new_calls']};calls=list(calls.values())
  costs.append({'阶段':name,'新增逻辑请求数':len(calls),'输入Token':sum(x.get('prompt_tokens') or 0 for x in calls),'输出Token':sum(x.get('completion_tokens') or 0 for x in calls),
    '缓存命中输入Token':sum(x.get('cached_input_tokens') or 0 for x in calls),'总Token':sum(x.get('total_tokens') or 0 for x in calls),
    '已知估算费用元':sum(x.get('estimated_yuan') or 0 for x in calls),'未知usage次数':sum(x.get('unknown_attempt_usage') or 0 for x in calls),
    '口径':'仅本次新增API；D候选依赖ABC，D成本不等于独立端到端成本；沿用已配置价格，并非网关账单'})
 issues=[
  ('C','T1-75441-M007','VOC-0284','卫生间地漏误标阳台地漏'),('C','T1-75441-M008','VOC-0201','厨房面积误标餐厅面积'),
  ('C','T2-2188228096999350274-V003','VOC-0134','学校毗邻误判学区划片'),
  ('C','T2-C-7963753211120747271-V001','项目C01','原文没有海晏却改归海晏'),
  ('C','T2-C-7963753211120747186-V001','项目P01','原文没有臻澐却新增臻澐'),
  ('D','T2-7055232109415196221-V003','VOC-0232','科技住宅泛称不能证明具体科技系统'),
  ('D','T2-7055232109415196221-V012','VOC-0168','平墅营销称谓不能直接证明别墅形态'),
  ('D','T2-7055232109415196221-V005','VOC-0483','有总价但无对应精装交付证据'),
  ('D','T2-7055232109415196221-V009','VOC-0483','有总价但无对应精装交付证据'),
  ('D','T2-7055232109415196221-V011','VOC-0483','有总价但无对应精装交付证据')]
 issue_rows=[dict(方案=k,unit_id=uid,标签或项目=tag,问题=why,证据来源='独立模型逐项核对原文与字典；待人工确认') for k,uid,tag,why in issues]
 changes=[]
 for k in 'ABCD':
  changes += [dict(方案=k,**r) for r in extra[k]['changes']]
 audits=[]
 for r in variants['D']['results']:
  for a in r['conservative_supplement_audit']:
   audits.append({'record_id':r['document']['record_id'],'unit_id':a['unit_id'],'候选ID':a['choice_key'],'模型盲审接受':a['accepted'],'决策':a['decision'],'协议问题':a['issues'],'说明':'机器接受不等于人工正确；已发现新增误标'})
 payload=copy.deepcopy(variants['D']);tables={};schemas={}
 for title,data in [('方案对照',rows),('费用汇总',costs),('已定位问题',issue_rows),('逐单元变化',changes),('D补标审计',audits)]:
  tables[title]=data;schemas[title]=list(data[0])
 # These two are D, not a promoted delivery; other routes are separate sheets.
 for title in ['产品信息单元','观点信息单元','来源追溯']:
  tables[title]=payload['tables'][title];schemas[title]=payload['schemas'].get(title) or list(tables[title][0])
 for k in 'ABC':
  for title in ['产品信息单元','观点信息单元']:
   name=k+'_'+title;tables[name]=variants[k]['tables'][title];schemas[name]=variants[k]['schemas'][title]
 payload['tables']=tables;payload['schemas']=schemas
 payload['summary']['note']='探索对照，不是正式交付：产品/观点主表为D；全部仍需人工审核；原默认v76保留。冻结切片边界，未评价重新切片效果。'
 args.output_dir.mkdir(parents=True,exist_ok=True)
 p.p.base.save_json(args.output_dir/'探索对照_工作簿源数据.json',payload)
 p.p.base.save_json(args.output_dir/'合同与字典核验.json',verification)
 p.p.base.save_json(args.output_dir/'对照指标与费用.json',{'rows':rows,'costs':costs,'D_tested_additions':92,'D_accepted_additions':43})
 print(json.dumps({'rows':rows,'costs':costs},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
