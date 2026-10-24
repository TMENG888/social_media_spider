"""Staged narrow modality check on the model-selected comparison evidence.

Only applies when the named actor matches the selected source speaker. It
does not borrow another commenter's lack of experience or select new facts.
"""
import re


_UNEXPERIENCED=r'没(?:有)?(?:听|体验|使用|用|乘坐)(?:过)?|未(?:亲自)?(?:听|体验|使用|用|乘坐)(?:过)?|未经体验'


def issues(fragment,entries,response):
    checks=response.get('checks') if isinstance(response,dict) else None
    if not isinstance(checks,list) or len(checks)!=1 or not isinstance(checks[0],dict):return []
    check=checks[0];keys=check.get('source_keys')
    if check.get('prose_key')!=fragment.get('prose_key') or not isinstance(keys,list):return []
    text=fragment.get('text') or '';lookup={e['source_key']:e for e in entries}
    comparative=r'优于|胜过|好于|更好|好一点|比[^。；]{0,16}好'
    if not re.search(comparative,text):return []
    selected=[lookup[k] for k in keys if isinstance(k,str) and k in lookup]
    # A full-source statement by another actor must not constrain this actor.
    conditional=[e for e in selected if isinstance(e.get('speaker'),str) and e['speaker'] in text
                 and re.search(_UNEXPERIENCED,e['text']) and '二选一' in e['text']
                 and re.search(r'也许|可能|倾向',e['text'])]
    if not conditional:return []
    actors={e['speaker'] for e in conditional}
    opposite=[e for e in selected if e.get('speaker') in actors and re.search(comparative,e['text'])
              and not re.search(r'也许|可能|倾向|二选一',e['text'])]
    if opposite:return []  # conflicting source statements require semantic review
    if re.search(_UNEXPERIENCED,text) and re.search(r'也许|可能|倾向|相对选择|二选一',text):return []
    return ['当前明确发言者的比较证据为未体验、二选一、也许较好；摘要的优于/更好遗漏未体验或相对倾向限定，须据原文重写']
