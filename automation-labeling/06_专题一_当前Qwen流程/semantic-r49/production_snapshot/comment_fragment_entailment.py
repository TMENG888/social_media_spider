"""Check one actual comment prose fragment per request, with full source context.

This is not comment slicing. Whole-summary coverage remains a separate audit;
these results never claim to prove full-source coverage.
"""
from concurrent.futures import ThreadPoolExecutor
import prose_audit_references as references
import comment_object_bindings as bindings

SYSTEM='''只输出JSON。独立核对当前唯一待审摘要片段是否由完整评论支持，不使用父文章补事实。
prose_catalog只有一个实际prose_key，只有其中text是待审命题；source_text是全部原评论。
不能把其他原文或其他摘要里有的概念当成这个待审命题已经说过的话。
逐项核对项目/地块/发言者对象、关系、模态和程度限定。该片含多个命题时，任一错误即unsupported。
对象不能向最近出现的项目名移植；指代承接不唯一时uncertain，不任选。
两个并列抱怨不证明因果；未体验且二选一可能更好不等于尚可、接受或满意。
保留可能、转述、相对比较、室内/室外等重要限定；不能把建议或估计当实测事实。
但不制造不存在的错误：原文“我觉得轮渡较慢”，摘要“乘客认为轮渡较慢”都是主观意见归因，不能仅因觉得换成认为就说升格客观事实。
待审片段若只说“交通堵，仅假期稍好”，不能因为原评论还谈声音就指控该片把堵车等同噪音；须先核实该片实际表达了什么。
“作者认为A不宜买；B措施效果未知”是两条并列说法，不要脑补因果。若实际写了“因为B效果未知所以A不宜买”才核因果依据。
此请求只审一片，不评全文主要事实覆盖，不因未写其他片的内容而拒绝当前有据命题。
source_keys只能选提供的原文实际键；assertion_quote必须是当前待审text里逐字存在的被审核表述，不改写成它没说过的断言。
返回{"checks":[{"prose_key":"当前实际键","assertion_quote":"当前text逐字表述",
"status":"supported/unsupported/uncertain","source_keys":["实际原文键"],
"object_binding_supported":true,"relation_supported":true,"modality_preserved":true,
"qualifiers_preserved":true,"why":"简短具体支持依据或实际错误","confidence":0.95}]}。
正确就supported，不为了挑错而挑错。四布尔项缺失或不确定不能通过，不输出分析过程，不重写文案。
''' + bindings.INSTRUCTION


def verify_one(fragment, source_catalog, response):
    checks=response.get('checks') if isinstance(response,dict) else None
    if not isinstance(checks,list) or len(checks)!=1 or not isinstance(checks[0],dict):
        return False,[{'accepted':False,'reason':'单命题审核未返回恰好一个决定'}]
    check=checks[0];keys=check.get('source_keys');quote=check.get('assertion_quote')
    valid_keys={e['source_key']:e for e in source_catalog}
    issues=[]
    if check.get('prose_key')!=fragment['prose_key']:issues.append('审核目标键不匹配')
    if not isinstance(quote,str) or not quote.strip() or quote not in fragment['text']:
        issues.append('被审核表述不是当前命题的逐字文本')
    if (not isinstance(keys,list) or not keys or any(not isinstance(k,str) or k not in valid_keys for k in keys)
            or len(keys)!=len(set(keys))):issues.append('单命题支持来源键缺失、重复或未知')
    if check.get('status')!='supported':issues.append('当前命题语义未通过：'+str(check.get('status')))
    for field in ('object_binding_supported','relation_supported','modality_preserved','qualifiers_preserved'):
        if check.get(field) is not True:issues.append('单命题维度未通过：'+field)
    confidence=check.get('confidence');why=check.get('why')
    if type(confidence) not in (int,float) or not .9<=confidence<=1:issues.append('单命题置信度不足或非法')
    if not isinstance(why,str) or not why.strip():issues.append('单命题支持理由缺失')
    # One request owns exactly one fragment/check, so a root-level binding
    # array has an unambiguous owner. Do not infer ownership in multi-check data.
    object_bindings=response.get('object_bindings',check.get('object_bindings'))
    issues.extend(bindings.verify(fragment['text'],source_catalog,object_bindings))
    audit=dict(check,accepted=not issues,issues=issues,verification_scope='单个实际摘要命题，不是全文coverage')
    return not issues,[audit]


def review(source,prose,doc,runner):
    # Lazy import avoids a cycle: the singleton protocol reuses verify_one.
    import comment_qualification_feedback_v57 as single_target
    catalog=references.payload(source,prose,'')
    fragments=catalog['prose_catalog'];sources=bindings.source_catalog(source)
    if not fragments:return False,[{'accepted':False,'reason':'没有有效待审摘要命题'}],[]
    def work(fragment):
        payload={'source_text':source,'source_evidence_catalog':sources,
                 'prose_catalog':[fragment],'fragment_only':True}
        calls=[];attempt_audit=[]
        for attempt in range(2):
            response,metrics=runner.call(single_target.SYSTEM,payload,doc,
                '评论单目标程序拥有属性引文-v11.47' if not attempt else '评论属性原文键协议恢复-v11.47')
            calls.append(metrics)
            okay,audit=single_target.verify(fragment,sources,response if metrics['status']=='success' else None)
            attempt_audit.extend(dict(a,protocol_attempt=attempt) for a in audit)
            if okay:break
            # A wrong key/quote is not proof that otherwise-correct prose is
            # wrong. Repair only references; never rewrite or approve prose here.
            checks=response.get('checks',[]) if isinstance(response,dict) else []
            if (not isinstance(checks,list) or not checks or not isinstance(checks[0],dict)
                    or checks[0].get('status')!='supported'
                    or any('不同评论轮次' in issue for a in audit for issue in a.get('issues',[]))):break
            payload=dict(payload,previous_response=response,reference_issues=audit)
        return okay,audit,attempt_audit,calls
    with ThreadPoolExecutor(max_workers=10) as pool:results=list(pool.map(work,fragments))
    # Only final decisions govern acceptance; failed reference attempts stay
    # in a separate audit field and cannot lower the accepted prose confidence.
    final_audit=[dict(a,reference_attempts=r[2]) for r in results for a in r[1]]
    return all(r[0] for r in results),final_audit,[m for r in results for m in r[3]]
