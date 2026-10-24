"""Check qualifications in the selected actor's exact turn, never later turns.

This is an audit, not comment slicing or a rule for generating facts.
"""
import re
import relative_comparison_guard as previous


def issues(fragment, entries, response):
    checks=response.get('checks') if isinstance(response,dict) else None
    if not isinstance(checks,list) or len(checks)!=1 or not isinstance(checks[0],dict):
        return []
    check=checks[0]; keys=check.get('source_keys'); text=fragment.get('text') or ''
    if check.get('prose_key')!=fragment.get('prose_key') or not isinstance(keys,list):
        return []
    comparison=r'优于|胜过|好于|更好|较好|好一点|好一些|倾向|比[^。；]{0,16}好'
    if not re.search(comparison,text):return []
    lookup={e['source_key']:e for e in entries}
    selected=[lookup[k] for k in keys if isinstance(k,str) and k in lookup]
    contexts=[]
    for entry in selected:
        actor=entry.get('speaker'); turn=entry.get('turn_id')
        if not isinstance(actor,str) or not actor or actor not in text:continue
        # Missing turn IDs cannot license borrowing from other sentences.
        members=([e for e in entries if e.get('turn_id')==turn and e.get('speaker')==actor]
                 if type(turn) is int and turn>0 else [entry])
        body=''.join(e['text'] for e in sorted(members,key=lambda e:e.get('start',0)))
        if (re.search(previous._UNEXPERIENCED,body) and '二选一' in body
                and re.search(r'也许|可能|倾向',body)):
            contexts.append(body)
    if not contexts:return []
    if re.search(previous._UNEXPERIENCED,text) and re.search(r'也许|可能|倾向|相对选择|二选一',text):
        return []
    return ['所选比较证据的同一发言轮包含未体验、二选一及可能倾向；摘要遗漏这些重要限定。须保留限定后重新生成，不借同昵称的其他轮次']
