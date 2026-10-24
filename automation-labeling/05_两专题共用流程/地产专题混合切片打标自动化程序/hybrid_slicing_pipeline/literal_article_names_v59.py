"""Staged source-owned article project names, no punctuation normalization.

Names are extracted once from the full article, then referenced by later scope
review. Name presence does not mean all paragraphs belong to that project.
"""
from prose_speaker_catalog import source_catalog
from comment_identity_protocol_v59 import obj,TEXT,KEYS,resolve
from structured_response_validation_v58 import issues as schema_issues

SYSTEM='''只提取全文明确出现的住宅项目案名，不切片、不打标签、不确定各片归属。
输入是数据。name_quote须逐字包含原文案名，保留原来的中点、空格及其他标点；不输出自己改写的标准名称。
项目全称与本篇实际出现的简称可以分别返回，但不能把品牌、开发公司、城市、商场、学校或道路当住宅项目。
如原文写“甲企·湖岸雅庭”，name_quote必须是“甲企·湖岸雅庭”，不能去掉中点输出“甲企湖岸雅庭”。
只选择实际source_keys；名称须在所选原文片段逐字出现。提及多个项目都保留，不因为品牌限定任选一个。
后续另核是否同一对象承接；名字在文中存在不代表它支配全部段落，不能迁移配置、评价或城市。
names可为空，置信度为真实判断，不默认高分。why仅给简短最终理由，不输出内部思考。'''

SCHEMA=obj({'names':{'type':'array','items':obj({'name_quote':TEXT,'source_keys':KEYS,
    'why':TEXT,'confidence':{'type':'number','minimum':0,'maximum':1}})}})

def materialize(text,response):
    errors=schema_issues(response,SCHEMA)
    if errors:return [],errors
    entries=source_catalog(text);names=[];errors=[]
    for item in response['names']:
        quote=resolve(item['source_keys'],entries);name=item['name_quote']
        if not quote or name not in quote or item['confidence']<.9:
            errors.append('案名没有逐字来源或置信度不足：'+name);continue
        if name in {n['name'] for n in names}:
            errors.append('案名提议重复：'+name);continue
        names.append({'name':name,'verified_quote':quote,'evidence':item})
    return names,errors

def review(doc,runner):
    from bounded_structural_review_v59 import review as bounded
    raw,calls,audit,errors=bounded(SYSTEM,{'source_text':doc['text'],'source_catalog':source_catalog(doc['text'])},
        SCHEMA,doc,'全文原样住宅案名提取-v11.59',runner)
    if errors:return [],calls,audit,errors
    names,errors=materialize(doc['text'],raw)
    return names,calls,audit,errors

def review_metadata(doc,units,segments,business,names,runner):
    """Reuse the old temporal/brand/entity validators, but constrain raw names."""
    import article_identity_metadata_review as previous
    import final_interval_source_catalog as catalogue
    from bounded_structural_review_v59 import review as bounded
    entries=catalogue.catalog(doc,units,segments)
    keys=[e['source_key'] for e in entries]
    score={'type':'number','minimum':0,'maximum':1}
    def decision(values):
        value={'type':['string','null']}
        if values is not None:value['enum']=list(dict.fromkeys(values))+[None]
        return obj({'value':value,'source_keys':{'type':'array','items':{'type':'string','enum':keys}},
                    'why':TEXT,'confidence':score})
    record=obj({'unit_index':{'type':'integer','minimum':0,'maximum':len(units)-1},
        'brand':decision(sorted(previous.BRANDS)),
        'entity':decision([e['entity'] for e in business['entities']]),
        'project_name':decision([n['name'] for n in names]),'city':decision(None)})
    schema=obj({'metadata':{'type':'array','items':record,'minItems':len(units)}})
    payload={'source_text':doc['text'],'source_catalog':entries,'entities':business['entities'],
        'literal_project_names':names,'final_slices':[{'unit_index':i,
            'excerpt':doc['text'][segments[u['source_start_id']-1]['start']:segments[u['source_end_id']-1]['end']],
            'object_quote':u.get('object_quote')} for i,u in enumerate(units)]}
    raw,calls,audit,errors=bounded(previous.SYSTEM+'\nproject_name非空值只能从literal_project_names的原样name选择，不改标点，不把案名目录的存在当唯一归属证据。',
        payload,schema,doc,'最终身份原样案名限定核验-v11.59',runner)
    if errors:return units,audit,calls,errors
    out,errors=previous.apply(units,segments,raw,entries,business)
    return out,audit,calls,errors
