"""Synthetic boundary challenges. Separate from sampled articles and gold anchors."""
import os,json,argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import delivery_v82 as v

CASES=[
 ('中文面宽','该户型面宽十二米。','VOC-0184','supported'),
 ('数字位置倒置','本套住宅采用17米面宽。','VOC-0184','supported'),
 ('中文面积单位','该户型建筑面积一百平方米。','VOC-0186','supported'),
 ('错用层高数值','这个户型面宽很好，层高3.5米。','VOC-0184','unsupported'),
 ('建筑面积对象错配','小区总建筑面积十万平方米，住宅户型尚未公布。','VOC-0186','unsupported'),
 ('不同房源装修口径','A房源毛坯售价500万元。B房源精装，尚未报价。','VOC-0483','unsupported'),
 ('营销别墅称谓','这套大平层有别墅般的居住体验。','VOC-0168','unsupported'),
]
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--output-dir',type=Path,required=True);ap.add_argument('--result-name',default='synthetic_challenges');a=ap.parse_args()
 v.core.activate();taxonomy=v.p.p.base.load_taxonomy(v.p.p.v.legacy.TAXONOMY);index={t['tag_id']:t for t in taxonomy}
 runner=v.p.p.base.ApiRunner(a.output_dir/'challenge_calls',10,key=os.getenv('YS_LLM_API_KEY'))
 def one(case):
  name,text,tid,expected=case;doc={'record_id':'SYNTHETIC-'+name,'topic':v.p.p.base.T1,'kind':'文章','text':text}
  result={'document':doc};row={'原文摘录':text};review=v.review_one(result,row,index[tid],runner,'context')
  oldpassed,hint=v.hard_check(index[tid],text)
  return {'案例':name,'原文':text,'标签路径ID':tid,'预期':expected,'原硬规则是否通过':oldpassed,
   '模型复核':review['verdict'],'符合预期':expected==review['verdict'],'说明':(review['decision'] or {}).get('why'),'审计':review}
 with ThreadPoolExecutor(max_workers=7) as pool:rows=list(pool.map(one,CASES))
 v.p.p.base.save_json(a.output_dir/(a.result_name+'.json'),{'synthetic':True,'note':'人工构造句式及对象边界测试，非真实样本准确率','cases':rows,'calls':runner.calls})
 print(json.dumps({'cases':len(rows),'matched':sum(x['符合预期'] for x in rows),'results':[{k:x[k] for k in ['案例','预期','原硬规则是否通过','模型复核','符合预期']} for x in rows]},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
