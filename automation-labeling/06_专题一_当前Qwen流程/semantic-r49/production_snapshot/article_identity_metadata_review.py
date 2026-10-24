"""Source-grounded metadata recheck after the final article boundaries.

Separates developer brand, legal entity, project and city. No factual labels,
configurations or attitudes are inherited from earlier article paragraphs.
"""
import copy
import math
from focused_summary_references import catalog
import final_interval_source_catalog as final_catalog

FIELDS=('brand','entity','project_name','city')
BRANDS={'中海','保利','招商','金茂'}
SYSTEM='''只返回JSON。本步骤只核最终文章切片的身份，不生成标签、摘要或配置。
source_text为完整原文，读取当前片及已验证的object_quote，判断身份承接是否唯一且未切换对象。
品牌组brand仅中海/保利/招商/金茂/null；设备品牌不是开发商品牌。
法律公司名称不能填入brand，项目名不是经营主体entity。
entity仅选经营主体字典且原文明示；不能把品牌自动改为字典公司的名称。
project_name是原文项目名，city须原文明确项目所在城市，不从公司注册地、热线区号推断。
免责声明/面积说明可承接明确单一项目身份，不因本片没重复案名就丢身份。
多项目比较不得任选一项目；无法唯一确认的字段value=null并说明具体原因。
每个字段选择原文实际source_keys，并说明当前片与其连续承接关系；不能借前文配置/情绪。
不能引用当前片结束后尚未介绍的信息；程序按实际位置核查。
返回{"metadata":[{"unit_index":0,"brand":{"value":null,"source_keys":[],"why":"依据或不确定原因","confidence":0.95},
"entity":{"value":null,"source_keys":[],"why":"依据或不确定原因","confidence":0.95},
"project_name":{"value":null,"source_keys":[],"why":"依据或不确定原因","confidence":0.95},
"city":{"value":null,"source_keys":[],"why":"依据或不确定原因","confidence":0.95}}]}。
恰好覆盖全部unit_index，不省略四个字段。'''
SYSTEM+='''
source_catalog是完整文章的原文目录，不是仅当前片。可以选择之前实际出现、未切换对象的身份键。
身份与配置分开：第一片明确“中海海上雅苑位于甲城”，下一片是该项目面积或预售证说明，
后片可承接品牌中海、项目海上雅苑、城市甲城的前文键；不能承接第一片设备、价格、面积或情绪。
“本片没重复案名/城市”“本片是行政免责声明”不构成身份必定未知的理由。仍须全文确为同对象。
反例：第一片中海甲项目，后来转换乙项目，不能让乙片继承甲身份；多项目比较也不能任选一名。
开发商法律公司不在entities字典时entity=null，但不因此把独立可核的brand/project_name/city一起清空。
理由只写最终依据，不输出自我思考、修正思考或与value矛盾的论述。
'''


def apply(units,segments,response,entries,business):
    out=copy.deepcopy(units);items=response.get('metadata') if isinstance(response,dict) else None
    if (not isinstance(items,list) or len(items)!=len(units)
            or any(not isinstance(x,dict) or type(x.get('unit_index')) is not int for x in items)
            or sorted(x['unit_index'] for x in items)!=list(range(len(units)))):
        return out,['最终身份元数据未唯一覆盖切片']
    lookup={e['source_key']:e for e in entries};issues=[]
    for item in items:
        i=item['unit_index'];end=segments[units[i]['source_end_id']-1]['end']
        decisions={};local=[]
        for field in FIELDS:
            decision=item.get(field)
            if not isinstance(decision,dict):local.append(field+'字段缺失');continue
            value=decision.get('value');confidence=decision.get('confidence');keys=decision.get('source_keys')
            if (not isinstance(decision.get('why'),str) or not decision['why'].strip()
                    or type(confidence) not in (int,float) or not math.isfinite(confidence) or not .9<=confidence<=1):
                local.append(field+'理由或置信度未通过');continue
            if value is None:
                if keys!=[]:local.append(field+'空值仍有来源键');continue
                decisions[field]=None;continue
            if (not isinstance(value,str) or not value.strip() or not isinstance(keys,list) or not keys
                    or len(keys)!=len(set(keys)) or any(not isinstance(k,str) or k not in lookup or lookup[k]['end']>end for k in keys)):
                local.append(field+'值或原文时序键未通过');continue
            if not any(value in lookup[k]['text'] for k in keys):local.append(field+'值未在实际原文出现');continue
            if field=='brand' and value not in BRANDS:local.append('法律主体或设备名不可作为品牌组');continue
            if field=='entity' and not any(e['entity']==value for e in business['entities']):
                local.append('经营主体不在业务字典');continue
            decisions[field]=value
        if decisions.get('entity') and not any(e['entity']==decisions['entity'] and e['brand']==decisions.get('brand') for e in business['entities']):
            decisions.pop('entity');local.append('品牌及经营主体字典关系不对应')
        # Never silently erase a failed field or fill it from a neighboring unit.
        out[i].update(decisions);out[i]['metadata_identity_audit']=copy.deepcopy(item)
        if local:
            message='切片'+str(i+1)+'身份元数据待核：'+'；'.join(local)
            issues.append(message);out[i].setdefault('uncertainties',[]).append(message)
    return out,issues


def review(doc,units,segments,business,runner):
    entries=final_catalog.catalog(doc,units,segments)
    payload={'source_text':doc['text'],'source_catalog':entries,'entities':business['entities'],
             'final_slices':[{'unit_index':i,'excerpt':doc['text'][segments[u['source_start_id']-1]['start']:segments[u['source_end_id']-1]['end']],
                 'object_quote':u.get('object_quote'),'identity_context_audit':u.get('identity_context_audit')}
                 for i,u in enumerate(units)]}
    calls=[];attempts=[];out=units;issues=[]
    for attempt in range(2):
        response,m=runner.call(SYSTEM,payload,doc,
            '最终边界身份目录元数据核查-v11.44' if not attempt else '最终身份目录元数据有界恢复-v11.44')
        calls.append(m)
        out,issues=apply(units,segments,response,entries,business) if m.get('status')=='success' else (units,['文章身份元数据API失败'])
        attempts.append({'response':response,'issues':issues})
        if not issues:break
        payload=dict(payload,previous_response=response,repair_issues=issues)
    return out,attempts,calls,issues
