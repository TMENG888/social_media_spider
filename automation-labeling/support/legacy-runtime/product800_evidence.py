"""Reuse v92 lossless evidence catalogue instead of generated free-text quotes."""
import copy
import qwen_reason_policy_v9917 as policy
import voc_batch_v99 as v

FORMAT_RULE = '''
本请求沿用原程序source_evidence证据编号模式。严禁生成或改写quotes。
labels.attribute_keys仅选当前unit_id的source_key；context_keys仅选全文目录的真实source_key。
fact_coverage.source_key也必须选当前unit_id的source_key。程序按编号回填逐字原文。
每个标签必须有当前片属性证据。完整单元Q编号可用于该片全文事实，但不要借其他单元的属性。
fact_coverage逐事实说明对应已选label_keys，确无适用项给no_label_reason。
输出字段以output_contract为准；旧协议中的quotes/context_quotes/quote由本次编号字段替代。
'''


def request(seed,items,index,business):
    # The original v92 catalogue includes each full unit plus sentence spans.
    catalog=v.supplement.evidence_catalog(seed['units'])
    payload=v.fields.request(seed,items,index,business)
    payload['source_evidence']=catalog
    payload['evidence_protocol']='v92 literal catalogue; current unit attribute keys only'
    schema=policy.schema([u['unit_id'] for u in items])
    unit=schema['properties']['units']['items']['properties']
    label=unit['labels']['items']['properties']
    del label['quotes'];del label['context_quotes']
    keys=[e['source_key'] for e in catalog]
    label['attribute_keys']={'type':'array','minItems':1,'items':{'type':'string','enum':keys}}
    label['context_keys']={'type':'array','items':{'type':'string','enum':keys}}
    unit['labels']['items']['required']=list(label)
    fact=unit['fact_coverage']['items']['properties'];del fact['quote']
    fact['source_key']={'type':'string','enum':keys}
    unit['fact_coverage']['items']['required']=list(fact)
    return payload,schema,catalog


def resolve(raw,catalog):
    result=copy.deepcopy(raw);idx={e['source_key']:e for e in catalog};errors={}
    for unit in result.get('units',[]):
        uid=unit['unit_id'];own=[]
        for tag in unit['labels']:
            keys=tag.pop('attribute_keys');contexts=tag.pop('context_keys')
            if any(k not in idx or idx[k]['unit_id']!=uid for k in keys):own.append('属性证据编号非当前片')
            if any(k not in idx for k in contexts):own.append('上下文证据编号不存在')
            tag['quotes']=[idx[k]['text'] for k in keys if k in idx]
            tag['context_quotes']=[idx[k]['text'] for k in contexts if k in idx]
            tag['evidence_keys_preserved']={'attribute_keys':keys,'context_keys':contexts}
        for fact in unit['fact_coverage']:
            key=fact.pop('source_key')
            if key not in idx or idx[key]['unit_id']!=uid:own.append('事实证据编号非当前片')
            fact['quote']=idx[key]['text'] if key in idx else ''
            fact['source_evidence_key']=key
        errors[uid]=own
    return result,errors


def normalize_role(raw,fields):
    """Only split actual ellipsis separators into separate literal quotes."""
    import re
    result=copy.deepcopy(raw);evidence=[];audit=[]
    for entry in raw.get('evidence',[]):
        quote=entry.get('quote') or '';text=fields.get(entry.get('field'),'')
        if quote in text:evidence.append(entry);continue
        parts=[s.strip() for s in re.split(r'…+|\.{3,}',quote) if s.strip()]
        if len(parts)>1 and all(s in text for s in parts):
            evidence.extend({'field':entry['field'],'quote':s} for s in parts)
            audit.append({'original':entry,'action':'省略号各段分别逐字定位，不伪装成连续引文'})
        else:evidence.append(entry)
    result['evidence']=evidence
    return result,audit
