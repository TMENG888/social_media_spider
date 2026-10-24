"""Staged bounded identity protocol repair; not active until explicitly wired in."""
import math
import re
import article_identity_references as references


CLARIFICATION='''
身份承接和配置借入是两回事。全文明确是单一项目且未切换对象时，面积免责声明也可承接该项目身份；
只赋予对象身份，绝不把前文设备、尺寸或态度借入当前片。比较文章、多项目清单仍须分别判断。
每个contexts项都返回unit_index、assigned、identity_key、why、confidence。不得遗漏confidence，
不得因协议错误自行补默认置信度。assigned=false代表确实不能确定归属，不是“本片没重复案名”。
'''
CLARIFICATION+='''
本任务的assigned仅表示身份承接，不表示本片继承过往配置。身份目录是全文目录，当前片可选此前身份键。
正例（独立合成）：前文明确“甲品牌甲城甲项目”，后片紧接“开发商...面积...预售证...”，
全文无对象转换时后片可选甲项目身份键；绝不把前文设备或态度抄入后片。
反例：前文甲项目后文转乙项目，或两个项目比较，不能任选甲身份。
不要以“本片未重复案名/是标准免责声明/禁止借配置”为唯一拒绝身份的理由。
若why既承认关联前文项目，又仅因未重复名字或不能借配置而assigned=false，必须独立重审矛盾。
'''


def semantic_conflicts(response):
    contexts=response.get('contexts',[]) if isinstance(response,dict) else []
    out=[]
    for c in contexts:
        if not isinstance(c,dict) or c.get('assigned') is not False:continue
        why=str(c.get('why') or '')
        associated=re.search(r'关联前文|指向前文|与前文.{0,12}(?:项目|关联)|连续承接',why)
        absent=re.search(r'未(?:包含|重复|提及).{0,12}(?:项目名称|案名)|配置.{0,12}(?:不能|不得).{0,12}(?:借|移植)',why)
        if associated and absent:out.append('身份承接理由承认前文关联却混用配置借入或未重复名字规则：切片'+str(c.get('unit_index')))
    return out


def protocol_issues(response, count, catalog):
    contexts=response.get('contexts') if isinstance(response,dict) else None
    if not isinstance(contexts,list) or len(contexts)!=count:
        return ['contexts未恰好覆盖每个最终切片']
    if any(not isinstance(c,dict) or type(c.get('unit_index')) is not int for c in contexts):
        return ['contexts项结构或unit_index类型无效']
    if sorted(c['unit_index'] for c in contexts)!=list(range(count)):
        return ['unit_index缺失、越界或重复']
    keys={e['source_key'] for e in catalog};issues=[]
    for c in contexts:
        i=c['unit_index'];confidence=c.get('confidence')
        if type(c.get('assigned')) is not bool:issues.append(f'切片{i}缺少布尔assigned')
        if (type(confidence) not in (int,float) or not math.isfinite(confidence)
                or not 0<=confidence<=1):issues.append(f'切片{i}缺少合法confidence')
        if not isinstance(c.get('why'),str) or not c['why'].strip():issues.append(f'切片{i}缺少理由')
        if c.get('assigned') is True:
            if not isinstance(c.get('identity_key'),str) or c['identity_key'] not in keys:
                issues.append(f'切片{i}身份键不在原文目录')
        elif c.get('assigned') is False and c.get('identity_key') is not None:
            issues.append(f'切片{i}assigned=false仍指定身份键')
    return issues


def review(doc, units, segments, catalog, slices, runner):
    payload={'source_text':doc['text'],'identity_catalog':catalog,'final_slices':slices}
    calls=[];attempts=[];response=None;issues=[];protocol=[];conflicts=[]
    for attempt in range(2):
        response,metrics=runner.call(references.SYSTEM+CLARIFICATION,payload,doc,
            '最终原文身份完整及矛盾核验-v11.44' if attempt==0 else '身份键缺项及矛盾有界恢复-v11.44')
        calls.append(metrics)
        protocol=protocol_issues(response,len(units),catalog) if metrics.get('status')=='success' else ['身份审核API失败']
        conflicts=semantic_conflicts(response) if not protocol else []
        issues=protocol+conflicts
        attempts.append({'response':response,'protocol_issues':protocol,'semantic_conflict_leads':conflicts})
        if not issues:break
        # Authentication handling remains owned by the shared API runner.
        payload=dict(payload,previous_response=response,protocol_issues=issues,
                     repair_instruction='重新按完整原文判断并输出所有contexts及必需字段，不沿用缺失字段，不添加默认置信度。')
    out,identity_issues=references.apply(units,segments,response if not protocol else None,catalog)
    if conflicts:identity_issues.append('文章对象承接审核仍有身份/配置规则矛盾，未强行赋身份：'+'；'.join(conflicts))
    return out,{'attempts':attempts,'protocol_issues':protocol,'semantic_conflict_leads':conflicts,'identity_issues':identity_issues},calls
