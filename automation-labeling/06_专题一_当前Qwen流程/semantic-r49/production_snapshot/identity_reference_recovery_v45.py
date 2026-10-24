"""Provide exact failed reference diagnostics; never auto-assign identities."""
import article_identity_metadata_review as previous
import final_interval_source_catalog as final_catalog


SYSTEM=previous.SYSTEM+'''
source_keys必须包含value原样出现的身份证据，不是仅证明当前片属于该项目的键。
身份承接时选前文真的含该名称的键；当前段上下文解释放why。不要求value每片重述。
例如前文键K1文字“甲品牌甲项目位于甲城”，后片键K2只有“面积210平方米”：
后片brand/project_name/city选择K1，不选不含身份名的K2；不得因后片无重复名称而填null。
value=null时source_keys必须[]，即使原文有字典外公司名也不把该证据放入空值键。
不得从法律公司的名称中取城市；应选确实介绍项目所在城市的证据。
恢复输入field_reference_diagnostics列出错误键及实际可用含名键，逐字段纠正；不是要求任选或自动继承。
'''


def diagnostics(units,segments,response,entries):
    items=response.get('metadata') if isinstance(response,dict) else None
    if not isinstance(items,list):return []
    lookup={e['source_key']:e for e in entries};out=[]
    for item in items:
        if not isinstance(item,dict):continue
        index=item.get('unit_index')
        if type(index) is not int or not 0<=index<len(units):continue
        end=segments[units[index]['source_end_id']-1]['end']
        for field in previous.FIELDS:
            d=item.get(field)
            if not isinstance(d,dict):continue
            value=d.get('value'); keys=d.get('source_keys')
            if value is None:
                if keys!=[]:out.append({'unit_index':index,'field':field,'issue':'空值的source_keys须为[]，不得把字典外名称当已赋值身份'})
                continue
            if not isinstance(value,str) or not value:continue
            candidates=[{'source_key':e['source_key'],'text':e['text'],'start':e['start'],'end':e['end']}
                        for e in entries if e['end']<=end and value in e['text']]
            if not isinstance(keys,list) or not keys or not any(k in lookup and value in lookup[k]['text'] and lookup[k]['end']<=end for k in keys):
                out.append({'unit_index':index,'field':field,'value':value,'selected_keys':keys,
                            'issue':'所选键不含value或超出本片时序；应核实实际含名证据及唯一承接关系',
                            'literal_name_references':candidates})
    return out


def review(doc,units,segments,business,runner):
    entries=final_catalog.catalog(doc,units,segments)
    payload={'source_text':doc['text'],'source_catalog':entries,'entities':business['entities'],
             'final_slices':[{'unit_index':i,'excerpt':doc['text'][segments[u['source_start_id']-1]['start']:segments[u['source_end_id']-1]['end']],
                 'object_quote':u.get('object_quote'),'identity_context_audit':u.get('identity_context_audit')}
                 for i,u in enumerate(units)]}
    calls=[];audit=[];out=units;errors=[]
    for attempt in range(2):
        response,m=runner.call(SYSTEM,payload,doc,'身份实际含名键审核-v11.45' if not attempt else '身份逐字段含名键诊断恢复-v11.45')
        calls.append(m)
        out,errors=previous.apply(units,segments,response,entries,business) if m.get('status')=='success' else (units,['身份元数据API失败'])
        details=diagnostics(units,segments,response,entries)
        audit.append({'response':response,'issues':errors,'field_reference_diagnostics':details})
        if not errors:break
        payload=dict(payload,previous_response=response,repair_issues=errors,field_reference_diagnostics=details)
    return out,audit,calls,errors
