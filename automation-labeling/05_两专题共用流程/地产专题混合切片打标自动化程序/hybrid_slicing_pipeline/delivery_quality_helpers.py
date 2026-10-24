"""Pure validators for the next acceptance revision; no API/database writes."""
import copy
import re
from difflib import SequenceMatcher


def missing_prose(value):
    return not isinstance(value,str) or value.strip().casefold() in {'','null','none','nan','undefined'}


def long_subclause_copy(source,prose):
    a=re.sub(r'[\s\W_]+','',source or '',flags=re.UNICODE)
    b=re.sub(r'[\s\W_]+','',prose or '',flags=re.UNICODE)
    if not b:return False
    longest=SequenceMatcher(None,a,b,autojunk=False).find_longest_match().size
    return longest>=25 and longest/len(b)>=.8


def scope_acceptance(unit,audit):
    """Keep local definition/protocol uncertainty on its own slice."""
    output=copy.deepcopy(unit)
    issues=list((output.get('self_check') or {}).get('issues') or [])
    issues.extend(audit.get('issues') or [])
    for item in audit.get('ambiguous') or []:
        issues.append('当前片标签待核：'+str(item.get('choice_key'))+' '+str(item.get('reason')))
    issues=list(dict.fromkeys(issues))
    output.setdefault('self_check',{})['issues']=issues
    output['self_check']['pass']=output['self_check'].get('pass') is True and not issues
    # Other slices' notes never enter this function; source-wide schema errors
    # remain separate and must still be checked by the owning materializer.
    output.setdefault('uncertainties',[])
    output['uncertainties']=list(dict.fromkeys(output['uncertainties']+issues))
    return output


def project_name_is_grounded(name,comment_quote,parent_quote,projects):
    if not isinstance(name,str) or not name.strip():return False
    quotes=(comment_quote or '')+' '+(parent_quote or '')
    if name in quotes:return True
    matches=[q for q in projects if name==q['name'] or name in q['aliases']]
    # Canonical dictionary name can be supported by a registered literal alias.
    # Never guess on a collision; quote-location remains a separate check.
    return len(matches)==1 and any(alias and alias in quotes for alias in matches[0]['aliases'])
