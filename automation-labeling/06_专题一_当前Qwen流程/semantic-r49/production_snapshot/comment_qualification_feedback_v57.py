"""Preserve every failed constraint in concise generation feedback.

Existing reference/semantic gates remain unchanged. Qualification diagnostics
run even when another gate already failed; they never approve prose.
"""
import comment_key_only_attribute_protocol_v47 as previous
import re

UNEXPERIENCED=r'没(?:有)?(?:听|体验|使用|用|乘坐|坐|见)(?:过)?|未(?:亲自)?(?:听|体验|使用|用|乘坐|坐|见)(?:过)?|未经体验'

def qualification_issues(fragment,entries,response):
    checks=response.get('checks') if isinstance(response,dict) else None
    if not isinstance(checks,list) or len(checks)!=1 or not isinstance(checks[0],dict):return []
    check=checks[0];keys=check.get('source_keys');text=fragment.get('text') or ''
    if check.get('prose_key')!=fragment.get('prose_key') or not isinstance(keys,list):return []
    if not re.search(r'优于|胜过|好于|更好|较好|好一点|好一些|倾向|比[^。；]{0,16}好',text):return []
    lookup={e['source_key']:e for e in entries};contexts=[]
    for key in keys:
        if key not in lookup:continue
        entry=lookup[key];actor=entry.get('speaker');turn=entry.get('turn_id')
        if not isinstance(actor,str) or not actor or actor not in text:continue
        members=([e for e in entries if e.get('turn_id')==turn and e.get('speaker')==actor]
            if type(turn) is int and turn>0 else [entry])
        body=''.join(e['text'] for e in sorted(members,key=lambda e:e.get('start',0)))
        if re.search(UNEXPERIENCED,body) and '二选一' in body and re.search(r'也许|可能|倾向',body):contexts.append(body)
    if not contexts:return []
    if re.search(UNEXPERIENCED,text) and re.search(r'也许|可能|倾向|相对选择|二选一',text):return []
    return ['所选比较证据同一发言轮明确未体验并作二选一不确定比较；摘要须保留未体验及可能性质，不因对象绑定另有错误而遗漏此项反馈']

GENERATION_INSTRUCTION='''
先核源文的重要限定，再生成新摘要，不是把previous_prose换词重复。
比较结论包含“未体验/没听过/未坐过”和“二选一/也许”时，保留未体验及相对、不确定性质。
合成例：原文“未坐过这种缆车，二选一也许缆车好一点；乘客说渡轮颠簸”，
可写“乘客称渡轮颠簸；回复者未体验缆车，仅猜二选一可能更好。”
不能写“回复者认为缆车较好/接受缆车”，那会漏掉未体验与可能性质。
长度有限可省昵称或次要附和，不能省改变意思的限定。对核心观点保留关键比较对象。
independent_prose_issues是实际失败项，列出的每个目标都要回到全文核查后修复；
已通过的其他命题不是错误，不为迎合反馈改掉正确事实。反馈不提供新事实。
每个object_quote只写当前目标摘要实际存在的名词；没写进摘要的另一比较对象不应伪造为其已表达的对象。
原文不明的对象不得补全。全评论不拆行，原始摘录不变，生成稿仍须原有独立语义和覆盖核验。
'''
SYSTEM=previous.SYSTEM+'\n各项限定核验独立执行，引用/绑定有错时也须如实指出模态与未体验限定的遗漏；不因别项失败而把qualifiers_preserved写true。'

def compact_feedback(checks):
    """Remove successful history/response envelopes, not failed evidence claims."""
    if not isinstance(checks,list):return checks
    result=[]
    for check in checks:
        if not isinstance(check,dict):continue
        if check.get('accepted') is True:continue
        item={key:check[key] for key in ('prose_key','assertion_quote','issues','why','reason','status','confidence') if key in check}
        if item:result.append(dict(item,accepted=False))
    return result

def verify(fragment, entries, response):
    okay,audit=previous.verify(fragment,entries,response)
    extra=qualification_issues(fragment,entries,response)
    if extra:
        # Independent diagnostics cannot convert any rejected record to a pass.
        if not audit:audit=[{'accepted':False,'issues':[]}]
        for item in audit:
            item['accepted']=False
            item.setdefault('issues',[]).extend(issue for issue in extra if issue not in item.get('issues',[]))
        okay=False
    return okay,audit
