"""Non-promoted delivery after model service failures.

Keeps the complete historical batch. Applies explicitly source-checked example
corrections, not the failed whole-rewrite prototypes. They remain human-review
proposals, not independent gold labels or evidence of global model accuracy.
"""
import argparse,copy,json,re
from pathlib import Path
import delivery_v87 as new
from delivery_v4 import save_json,label_json
base=new.base

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--prior',type=Path,required=True);ap.add_argument('--output-dir',type=Path,required=True);a=ap.parse_args()
    previous=json.loads(a.prior.read_text(encoding='utf-8'));results=copy.deepcopy(previous['results']);byid={r['document']['record_id']:r for r in results}
    taxonomy=base.load_taxonomy(new.earlier.support.previous.p.p.v.legacy.TAXONOMY);tags={t['tag_id']:t for t in taxonomy};changes=[]
    def remove_row(result,uid,reason):
        pos=next(i for i,u in enumerate(result['rows']) if u['unit_id']==uid);row=result['rows'].pop(pos);trace=result['traces'].pop(pos)
        e={'原单元ID':uid,'原文':trace['原文证据'],'起点':trace['起点'],'终点':trace['终点'],'原因':reason,'原标签明细':row['标签明细'],'排除校验':trace}
        result.setdefault('excluded_intervals',[]).append(e);result['audit'].append({'原因':reason,'排除区间':e});changes.append({'unit_id':uid,'处理':'移出本版主表，保留排除审计','原因':reason})
    hk=byid['T1-8000912876517501741'];r=hk['rows'][0];t=hk['traces'][0]
    assert '5房5套設計' in r['原文摘录']
    r['标签明细']=[label_json(tags['VOC-0180'])]
    r['打标说明']='VOC-0180｜对象=本户型｜证据：5房5套設計｜理由：原文明确户型的房间及套房组成，可记录标准户型配置；不推导主卧数量，实用面积也不换成建筑面积。'
    r['具体产品做法']='采用5房5套户型配置，实用面积为4,732呎。'
    r['备注']='标准户型为本次依据原文及字典核对的替代建议，待人工最终确认；原文未说明开发品牌、经营主体或案名。'
    r['验收状态']='需人工审核';t['本次证据核查提案']={'标签':'VOC-0180','原文':'5房5套設計','身份未推断':True,'性质':'证据核查提案，非全批API改善证明'}
    changes.append({'unit_id':r['unit_id'],'处理':'补标准户型替代标签，修产品做法','原因':'5房5套描述户型构成，不等于5主卧；实用面积不改建筑口径'})
    stone=hk['rows'][1];assert '全石灰岩外牆' in stone['原文摘录']
    stone['具体产品做法']='采用全石灰岩外墙，配置1,608呎花园和1,057呎天台。'
    stone['备注']+='；本次转写已去除“纽约豪宅”这一无据地点判断；纽约只修饰设计师，品牌及项目仍待核。'
    changes.append({'unit_id':stone['unit_id'],'处理':'修正产品做法地点幻觉','原因':'纽约是设计师背景，不是房屋所在地'})
    sea=hk['rows'][2];sea['备注']='原文有270度海景及邻近第三方私人会所事实；当前专题一产品字典未找到专用标签，不能硬套自建会所或园区景观。保留待人工确认字典缺口，不当作无关内容删除。'
    sea['验收状态']='需人工审核'
    remove_row(hk,'T1-8000912876517501741-M004','仅重复前片已经保留的实用面积，其余为预约、广告日期和中介代理信息；没有新的适用产品标签。实用面积不能标为建筑面积。')
    pol=byid['T1-8000912876517501943'];first=pol['rows'][0];assert any(t['标签路径ID']=='VOC-0186' for t in first['标签明细'])
    first['打标说明']+='\n面积口径佐证（全文上下文）：以上面积均为建筑面积。该佐证与120—180㎡户型为同一项目，不在末片重复统计建筑面积事实。'
    pol['traces'][0]['面积口径上下文证据']=[{'quote':'以上面积均为建筑面积','start':pol['document']['text'].index('以上面积均为建筑面积'),'end':pol['document']['text'].index('以上面积均为建筑面积')+len('以上面积均为建筑面积')}]
    remove_row(pol,'T1-8000912876517501943-M004','120㎡和180㎡面积事实已归入本篇M001；保留全文末尾建筑面积口径作为M001上下文证据。其余为通勤配套、售证及开发公司背景，不再生成一个无新产品标签的重复单元。')
    comment=byid['T2-C-7963753211120747176'];u=comment['rows'][0]
    assert '噪音就几秒钟' in u['原始摘录']
    u['观点摘要']='评论认为飞机降落时看起来较吓人，但噪音仅持续几秒、班次不多，实质影响有限。'
    u['备注']+='；本次原文核对：保留“看着吓人”，不加原文未说明的“声音较大”。'
    u['验收状态']='需人工审核';changes.append({'unit_id':u['unit_id'],'处理':'忠实压缩评论摘要','原因':'看着吓人不是声音较大；不把父文体验加入评论'})
    # Incomplete model requests are not re-labelled as completed experiments.
    for result in results:
        for u in result['rows']:u['验收状态']='需人工审核'
    p=base.export(a.output_dir,results,previous['sampling'],taxonomy,previous['business'],None,'api',False)
    p['summary'].update(version='delivery-v88-safe-historical-batch-20261010',
        pipeline='历史完整批次保守整理＋已知事实核查提案；新程序全批API重测未完成',
        note='v85/v86重写候选未晋升。v87少样本已发起，模型服务最小请求亦超时，未完成全批重测。本版保留上批源记录，并修正明确案例；全部需人工审核，不是模型总体准确率改善证明。')
    p['delivery_changes']=changes;p['new_test_status']={'new_full_batch_completed':False,'successful_v87_call_caches':10,'complete_new_source_checkpoints':1,'reason':'模型服务最小请求超时，停止重复请求；无usage请求费用未知'}
    p['tables']['本轮修正与测试状态']=changes
    p['execution_manifest']=copy.deepcopy(previous.get('execution_manifest',{}));save_json(a.output_dir/'delivery_results.json',p)
    save_json(a.output_dir/'new_test_status.json',p['new_test_status']);print(json.dumps({'summary':p['summary'],'changes':changes,'new_test_status':p['new_test_status']},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
