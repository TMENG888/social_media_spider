"""D: baseline-preserving, blind per-label verification of C's additions.

No baseline removal, no metadata changes, no slice or prose changes. This is
an exploratory supplement, not a guarantee of correct or exhaustive labels.
"""
import argparse
import copy
import json
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import delivery_v76 as original
import delivery_v11 as pipeline
from bounded_visible_contract_v60 import review
from comment_identity_protocol_v59 import obj,TEXT
from experiment_routes_v78 import IDS,definitions,CONF
from evaluate_independent_label_anchors_v59 import evaluate
from compare_mapreduce_v76 import EXTRA,stats

SYSTEM='''本轮盲审一个标签，不看上一模型的选择、理由和摘要。输入只含原文与真实字典定义。
先说明原文的实际对象、实际属性，再检查是否严格属于完整标签路径和定义。
只有属性证据在source_text当前切片内才可支持；full_source_context只用于确认对象指代，不能补片外事实。
“卫生间地漏”不属于阳台地漏；“厨房10㎡”不属于餐厅尺寸；学校毗邻不证明学区划片。
“网签均价/成交价”不证明毛坯单价或毛坯总价；毛坯价格标签需要明确毛坯口径。
“产品适合二胎家庭”是作者营销描述，不证明客户本人家庭需求或消费观。
“社区底商”不证明餐饮设施；泛称生活气息不证明本人关注商业配套。
既有入住四年、自述室外听得到飞机且室内听不到属于噪音场景；不能要求负面或实测。
只有飞机视频文字，不可推导声音或噪音。本人明确需要地铁可记录交通关注，不能跨发言者。
家政间存在不能证明面积；4室2厅3卫可支持卫生间数量3；例子不是必须逐字出现。
门庭、园林、户内精装不同对象；法式装修风格不证明色彩；现有住宅层高不证明土地规划条件。
反例只是一般约束，实际仍按当前完整字典定义与源文判定，不能凭例子强填标签。
property_quote、object_quote必须是对应原文连续逐字引文，不拼省略号。
不支持/无法确定是有效结果，无需为补标提高置信度。why只写最终依据。'''
SCHEMA=obj({'supported':{'type':'boolean'},'actual_object':TEXT,'actual_property':TEXT,
    'object_matches':{'type':'boolean'},'property_matches':{'type':'boolean'},
    'modality_preserved':{'type':'boolean'},'inference_free':{'type':'boolean'},
    'property_quote':{'type':'string'},'object_quote':{'type':'string'},'why':TEXT,'confidence':CONF})

def run(result,candidate,taxonomy,runner):
    index=pipeline.p.v.registry(taxonomy,result['document']['topic'])
    proposed={r['unit_id']:r for r in candidate['rows']}
    pairs=[]
    for i,row in enumerate(result['rows']):
        old={t['标签路径ID'] for t in row['标签明细']}
        for tag in proposed[row['unit_id']]['标签明细']:
            if tag['标签路径ID'] not in old:pairs.append((i,'D'+tag['标签路径ID'].split('-')[1]))
    def one(pair):
        i,key=pair;row=result['rows'][i]
        text=row.get('原文摘录',row.get('原始摘录'))
        req={'source_text':text,'full_source_context':result['document']['text'],
             'source_kind':result['document']['kind'],'label_definition':definitions({key:index[key]})[0]}
        raw,cc,aa,ee=review(SYSTEM,req,SCHEMA,result['document'],'路线D新增标签逐项盲审-v79',runner)
        accepted=bool(raw and not ee and raw['supported'] and raw['confidence']>=.90 and all(raw[k] for k in
            ('object_matches','property_matches','modality_preserved','inference_free')) and raw['property_quote']
            and raw['property_quote'] in text and raw['object_quote'] and raw['object_quote'] in result['document']['text'])
        return pair,raw,cc,aa,ee,accepted
    with ThreadPoolExecutor(max_workers=10) as pool:checked=list(pool.map(one,pairs))
    out=copy.deepcopy(result);audits=[]
    for (i,key),raw,cc,aa,ee,accepted in checked:
        out['calls']+=cc
        audits.append({'unit_id':out['rows'][i]['unit_id'],'choice_key':key,'accepted':accepted,'decision':raw,'audit':aa,'issues':ee})
        if accepted:
            row=out['rows'][i];trace=out['traces'][i]
            row['标签明细'].append(pipeline.p.base.label_json(index[key]))
            row['打标说明']+='\n'+index[key]['tag_id']+'｜对象：'+raw['actual_object']+'｜属性证据：'+raw['property_quote']+'｜理由：'+raw['why']
            row['备注']+='；新增标签经逐项盲审，仍需独立人工核验：'+index[key]['tag_id']
            row['验收状态']='需人工审核'
            trace.setdefault('保守增补证据',[]).append(dict(raw,tag_id=index[key]['tag_id']))
    out['conservative_supplement_audit']=audits
    return out

def main():
    p=argparse.ArgumentParser();p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--candidate',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True)
    a=p.parse_args();original.activate();read=lambda f:json.loads(f.read_text(encoding='utf-8'))
    before=read(a.baseline);candidate=read(a.candidate);by={r['document']['record_id']:r for r in candidate['results']}
    selected=[r for r in before['results'] if r['document']['record_id'] in IDS]
    taxonomy=pipeline.p.base.load_taxonomy(pipeline.p.v.legacy.TAXONOMY)
    runner=pipeline.p.base.ApiRunner(a.output_dir,10,key=os.getenv('YS_LLM_API_KEY'))
    signature=pipeline.p.base.digest(Path(__file__).read_text(encoding='utf-8'))
    def work(r):
        f=a.output_dir/'documents'/(pipeline.p.base.digest({'code':signature,'result':r,'candidate':by[r['document']['record_id']]})+'.json')
        if f.exists():return read(f)
        out=run(r,by[r['document']['record_id']],taxonomy,runner);pipeline.p.base.save_json(f,out);return out
    results=[]
    with ThreadPoolExecutor(max_workers=10) as pool:
        for f in as_completed([pool.submit(work,r) for r in selected]):
            results.append(f.result());print(json.dumps({'completed':len(results),'planned':18}),flush=True)
    order={r['document']['record_id']:i for i,r in enumerate(selected)};results.sort(key=lambda r:order[r['document']['record_id']])
    data=pipeline.p.base.export(a.output_dir,results,before['sampling'],taxonomy,before['business'],runner,'api',True)
    data['summary'].update(version='delivery-v76.4-conservative-v79',planned_articles=8,
        note='针对性18来源保守增补实验，仅逐项盲审新增标签；旧标签、项目、边界和文案保留，非全量准确率。')
    data['execution_manifest']={'requested_record_ids':IDS,'scope':'针对性子集','seed':None}
    pipeline.p.base.save_json(a.output_dir/'delivery_results.json',data)
    ref=read(Path(__file__).with_name('independent_label_anchors_v59.json'));ref['anchors']+=EXTRA
    report={'baseline':evaluate(dict(before,results=selected),ref),'D':evaluate(data,ref),'counts':stats(data),
        'tested_additions':sum(len(r['conservative_supplement_audit']) for r in results),
        'accepted_additions':sum(x['accepted'] for r in results for x in r['conservative_supplement_audit']),
        'new_calls':runner.calls,'note':'未修项目/误标，不自动替换默认入口；没有人工完整金标准。'}
    pipeline.p.base.save_json(a.output_dir/'supplement_comparison.json',report)
    print(json.dumps({k:report[k] for k in ['counts','tested_additions','accepted_additions']},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
