"""Model owns semantic grouping; program owns literal object evidence."""
import copy
import final_group_protocol_v44 as previous


SYSTEM=previous.SYSTEM.replace('"object_source_quotes":["完整原文中的逐字对象短引文"]',
    '"object_references":[{"source_unit_key":"实际原文键","object_quote":"该键中逐字对象名词"}]')+'''
object_references只返回实际键和短对象名词，如“卫生间”，不要返回整段配置、拼接句或省略号。
程序从该键持有原文；你只选该键真实包含的名词及同一方案。不得使用不存在的引文或别处的对象。
不返回object_source_quotes旧字段。多成员组必须有object_references；单成员组不需要。
输出只写最终一致分组，why只写最终依据，不保留思考过程、旧方案或“修正如下”等废弃分组。
先逐项按actual_source_keys核对members原序恰好一次，再核同对象同主题及bridge/frame，最后输出JSON。
'''


def apply(doc,plan,segments,response):
    candidate=copy.deepcopy(response)
    groups=candidate.get('groups') if isinstance(candidate,dict) else None
    if not isinstance(groups,list):return plan,['最终分组列表缺失']
    entries=previous.grouping.catalog(doc,plan,segments)
    lookup={e['source_unit_key']:e for e in entries};errors=[]
    for index,group in enumerate(groups):
        if not isinstance(group,dict):continue
        members=group.get('members')
        if not isinstance(members,list) or len(members)<2:continue
        refs=group.get('object_references')
        if not isinstance(refs,list) or not refs:
            errors.append('组'+str(index)+'缺少新协议对象名词原文键');continue
        quotes=[]
        for ref in refs:
            key=ref.get('source_unit_key') if isinstance(ref,dict) else None
            quote=ref.get('object_quote') if isinstance(ref,dict) else None
            if not isinstance(key,str) or key not in lookup or not isinstance(quote,str) or not quote.strip() or quote not in lookup[key]['text']:
                errors.append('组'+str(index)+'对象键或逐字名词无效，禁止省略号拼接');continue
            quotes.append(quote)
        group['object_source_quotes']=quotes
    if errors:return plan,errors
    out,errors=previous.apply(doc,plan,segments,candidate)
    if not errors:out['post_split_raw_group_protocol']=copy.deepcopy(response)
    return out,errors


def review(doc,plan,segments,runner):
    if doc.get('kind')!='文章' or len(plan['units'])<2:return plan,[],[],[]
    entries=previous.grouping.catalog(doc,plan,segments);expected=[e['source_unit_key'] for e in entries]
    payload={'source_text':doc['text'],'topic':doc['topic'],'unit_catalog':entries,'actual_source_keys':expected}
    calls=[];audit=[];out=plan;errors=[]
    for attempt in range(2):
        response,m=runner.call(SYSTEM,payload,doc,'最终语义分组逐字对象键-v11.45' if not attempt else '最终分组对象键及完整顺序恢复-v11.45')
        calls.append(m)
        out,errors=apply(doc,plan,segments,response) if m.get('status')=='success' else (plan,['最终语义分组API失败'])
        coverage=previous.coverage_issues(response,expected)
        audit.append({'response':response,'issues':errors,'key_coverage':coverage})
        if not errors:break
        payload=dict(payload,previous_response=response,repair_issues=errors,**coverage)
    return out,audit,calls,errors
