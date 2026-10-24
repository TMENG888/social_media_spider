"""Prepare one reader-facing workbook input; preserve authoritative JSON."""
import copy
import json
from pathlib import Path
import delivery_v8 as p


def main():
    folder=Path('test_results_v8_integrated_20261009_api')
    original=json.loads((folder/'delivery_results.json').read_text(encoding='utf-8'))
    data=copy.deepcopy(original)
    ledger=json.loads((folder/'experiment_cost_ledger.json').read_text(encoding='utf-8'))
    checks=json.loads((folder/'dictionary_backfill_verification.json').read_text(encoding='utf-8'))
    improvements=[
        {'问题':'模型首轮遗漏','已落实机制':'完整适用字典分支覆盖；候选并集；终审包括被否定候选；按切片重新落标',
         '实际验证':'独立户型面积、主卧布局与2卫/3卫/4卫数量等；39个已知证据检查通过'},
        {'问题':'标签名称回填失败','已落实机制':'固定字典选择编号回填ID、编号、五级路径与强调方向；重名不猜',
         '实际验证':f"{checks['checked_delivered_tags']}个输出标签与原字典逐项一致；源字典无编号的VOC-0489保留null"},
        {'问题':'程序规则误删','已落实机制':'允许同对象上下文；逐字引用重新定位；识别户型数字简写和中文数量',
         '实际验证':'含整套建面与客厅8.5米同句仍保留房间尺度；3房2厅2卫保留数量'},
        {'问题':'切片合并多个独立对象','已落实机制':'模型全文判断对象起点，程序回填连续终点；拆后重新核查标签',
         '实际验证':'190/225/245/278/281㎡户型各自成片，278㎡次卧与281㎡衣帽间不在介绍中间截断'},
        {'问题':'召回扩大造成错标','已落实机制':'敏感对象归属独立审核；实体设施、运营权益与营销推断分开',
         '实际验证':'外部商场不标住宅公区商业；南北双阳台不推导通风；父文章设施不继承为评论事实'},
        {'问题':'产品做法照搬或新增含义','已落实机制':'截取原文检测、单独转写及逐事实证据校验；失败保留待复核而非复制',
         '实际验证':'中西双厨不改成两个独立厨房；保留各对象尺寸、配置及预留状态'},
        {'问题':'测试通过被误认为全量准确','已落实机制':'程序合同、已知证据回归、语义歧义与人工审核分开记录',
         '实际验证':'尚有人工审核单元及空文案；不声称零漏标、零错标或已完成人工验收'},
    ]
    fees=[
        {'口径':'当前结果关联的历次请求','已知估算费用元':data['summary']['estimated_yuan'],
         '未知计价或usage请求数':data['summary']['unknown_usage_or_price_calls'],
         '说明':'包含所复用的上游字典审核与本版校验，不是只做首轮API的单价，也不是完整账单。'},
        {'口径':'已保存v7/v8试验调用，含失败与多轮修复，去除复制缓存',
         '已知估算费用元':ledger['known_estimated_yuan'],'未知计价或usage请求数':ledger['calls_with_unknown_price_or_usage'],
         '说明':ledger['limitations']},
        {'口径':'已知价格条件','已知估算费用元':None,'未知计价或usage请求数':None,
         '说明':'仅输入≤32K已公布档：普通输入0.2元/百万Token、缓存命中输入0.04元/百万Token、输出0.8元/百万Token。未确认的档位不按零计费。'},
    ]
    data['tables']['改进与验证']=improvements;data['schemas']['改进与验证']=list(improvements[0])
    data['tables']['费用口径']=fees;data['schemas']['费用口径']=list(fees[0])
    continuations=[]
    for table,rows in list(data['tables'].items()):
        for row_index,row in enumerate(rows,1):
            for key,value in list(row.items()):
                text=json.dumps(value,ensure_ascii=False,separators=(',',':')) if isinstance(value,(dict,list)) else str(value or '')
                if len(text)<=32000:continue
                parts=[text[i:i+1200] for i in range(0,len(text),1200)]
                for i,part in enumerate(parts,1):
                    continuations.append({'原表':table,'数据行序号':row_index,'unit_id':row.get('unit_id'),
                        'record_id':row.get('record_id'),'原字段':key,'分段序号':i,'总段数':len(parts),'审计内容':part})
                row[key]=f'长审计续页：{table}，数据行{row_index}，字段{key}，共{len(parts)}段；原始JSON完整保留。'
    if continuations:
        data['tables']['长审计续页']=continuations;data['schemas']['长审计续页']=list(continuations[0])
    # Outputs first; provenance and terminal audits to the right.
    order=['改进与验证','产品信息单元','观点信息单元','人工审核','渠道覆盖','抽样文章清单','费用口径','Token费用',
        '已知问题锚点对比','逐来源版本对比','排除及异常','来源追溯','全字典覆盖审计','质量复查线索','证据待复核标签','长审计续页']
    data['tables']={name:data['tables'][name] for name in order if name in data['tables']}
    p.base.save_json(folder/'workbook_input.json',data)
    print(p.base.dumps({'workbook_sheets':len(data['tables'])+1,'continuation_rows':len(continuations),
        'authoritative_json_unchanged':True,'known_cost_yuan':ledger['known_estimated_yuan']}))


if __name__=='__main__':main()
