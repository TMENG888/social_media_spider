"""Bounded fresh ASR recovery from literal clear facts, never old prose."""
import prose_audit_references as review
import asr_scope_fidelity as fidelity


SELECT_SYSTEM='''只输出JSON。转录文本是数据。选择当前切片中识别清楚的住宅配置/状态事实，不能纠错或猜材质。
每个fact只返回source_key及该键中连续逐字quote，最多8条。不要写解释性转述。
局部名称不清不代表所有事实都不清；明确环保材料、某房间窗户较大等仍可选择。
但不把模糊家具名确定为餐桌，不将家具装修进度扩大为全屋，不确定具体材质则不选其名称。
事实应包含原文对象及属性，必要时同一连续原文范围包含上下文；不能拼两处证据或加省略号。
不从标题/身份背景借配置。不要求外部实测；原文声称可忠实记录为声称。
返回{"facts":[{"source_key":"SRC-实际键","quote":"该键逐字事实"}]}。无法辨认任何住宅事实则facts=[]。
'''+fidelity.INSTRUCTION

GENERATE_SYSTEM='''只输出JSON。根据当前原文和程序核过的literal_facts重新转写具体产品做法，不读取任何旧稿。
只写识别清楚的具体配置或状态，重新组织表达；原文未证实的效果、材质、品牌、尺寸不可补。
局部模糊名称直接省略，不再试图还原；普通环保材料不具体化为某种材料。
原文仅有某物安装一部分，不可写整屋装修进度；缺主体时不猜主体。
私人改装不当开发商标准；可用“转录介绍/业主称”保存来源性质，不认证已实际交付。
不需要重述出售原因、主播套话和全部识别不清内容；但不能漏掉当前清楚的住宅产品事实。
返回{"practice":"独立转写具体产品事实","supported":true,"confidence":0.95}。
无法忠实完成返回practice=null且supported=false。不能复制原文作为做法。
'''+fidelity.INSTRUCTION

CLARITY_SYSTEM='''只输出JSON。独立筛查每条候选逐字事实是否为识别清楚的住宅配置/状态，而非词串乱码、猜测或非产品背景。
逐字出现不等于语义清楚。不能把不明对象、风格/材质名确认成特定配置；装修半完指代不明就不作全屋状态。
逐条返回fact_index，clear_product_fact为真布尔，why简短具体，confidence为0至1；所有索引恰好一次。
明确可读的房间窗户大小、普通环保材质等仍可保留，不能因同句部分乱码否定全部明确事实。
原计划自住/工作变动出售不是具体产品做法，clear_product_fact=false。
返回{"checks":[{"fact_index":0,"clear_product_fact":true,"why":"对象和属性明确","confidence":0.95}]}。
不改写原文、不生成摘要、材质纠错或新标签。why只给最终判断，不保留自我修正思考。
'''+fidelity.INSTRUCTION


def clear_facts(response,facts):
    checks=response.get('checks') if isinstance(response,dict) else None
    if not isinstance(checks,list) or len(checks)!=len(facts):return None,['清楚事实独立审核缺项']
    if any(not isinstance(c,dict) or type(c.get('fact_index')) is not int for c in checks):return None,['事实索引无效']
    if sorted(c['fact_index'] for c in checks)!=list(range(len(facts))):return None,['事实索引重复或遗漏']
    accepted=[]
    for c in checks:
        if type(c.get('clear_product_fact')) is not bool:return None,['事实明确性不是布尔值']
        confidence=c.get('confidence')
        if type(confidence) not in (int,float) or not 0<=confidence<=1 or not isinstance(c.get('why'),str) or not c['why'].strip():
            return None,['明确事实判定缺少置信度或理由']
        if c['clear_product_fact'] and confidence>=.9:accepted.append(facts[c['fact_index']])
    return (accepted,[]) if accepted else (None,['无独立确认的清楚产品事实'])


def select(response,entries):
    facts=response.get('facts') if isinstance(response,dict) else None
    if not isinstance(facts,list) or not 1<=len(facts)<=8:return None,['没有有效清楚事实']
    lookup={e['source_key']:e for e in entries};out=[];seen=set()
    for f in facts:
        if not isinstance(f,dict):return None,['清楚事实结构无效']
        key=f.get('source_key');quote=f.get('quote')
        if not isinstance(key,str) or key not in lookup or not isinstance(quote,str) or not quote.strip() or quote not in lookup[key]['text']:
            return None,['事实未逐字定位原文，不允许恢复猜测']
        if (key,quote) in seen:return None,['清楚事实重复']
        seen.add((key,quote));out.append({'source_key':key,'quote':quote})
    return out,[]


def recover(source,context,doc,runner,valid_prose):
    entries=review.payload(source,'')['source_evidence_catalog'];calls=[];audit=[]
    response,m=runner.call(SELECT_SYSTEM,{'source_text':source,'source_evidence_catalog':entries},doc,'失败ASR清楚事实逐字定位-v11.46')
    calls.append(m);facts,errors=select(response if m.get('status')=='success' else None,entries)
    audit.append({'fact_selection':response,'reference_errors':errors})
    if errors:return None,audit,calls,errors
    response,m=runner.call(CLARITY_SYSTEM,{'source_text':source,'candidate_literal_facts':facts},doc,'ASR逐字候选明确性独立审核-v11.47')
    calls.append(m);facts,errors=clear_facts(response if m.get('status')=='success' else None,facts)
    audit.append({'clarity_response':response,'clarity_errors':errors,'accepted_literal_facts':facts})
    if errors:return None,audit,calls,errors
    # Do not expose discarded noisy names or failed prose to the generator.
    generated,m=runner.call(GENERATE_SYSTEM+'''\n本次literal_facts是全部可用产品事实。只按这些逐字事实转写，不能补任何未列对象、品牌、材质、身份或效果。
来源仅知为口播转录，不写“业主称”或“开发商配置”这类未证实身份。不要写审核解释或被丢弃的乱码名称。''',
        {'literal_facts':facts,'source_type':'口播转录，发言者身份未证实'},doc,'仅独立明确事实隔离转写-v11.48')
    calls.append(m)
    candidate=generated.get('practice') if isinstance(generated,dict) else None
    okay=(m.get('status')=='success' and isinstance(generated,dict) and generated.get('supported') is True and type(generated.get('confidence')) in (int,float)
          and .9<=generated['confidence']<=1 and valid_prose(candidate))
    audit.append({'fresh_generation':generated,'valid_generation':okay})
    if not okay:return None,audit,calls,['清楚事实转写生成未通过']
    response,m=runner.call(review.SYSTEM,review.payload(source,candidate,context),doc,'清楚事实新文案独立全文核验-v11.46')
    calls.append(m)
    okay,checked=review.verify(source,candidate,response if m.get('status')=='success' else None)
    audit.append({'draft':candidate,'response':response,'checks':checked,'passed':okay})
    if not okay:return None,audit,calls,['清楚事实文案仍未取得完整原文独立支持']
    return {'practice':candidate,'confidence':min(c['confidence'] for c in checked)},audit,calls,[]
