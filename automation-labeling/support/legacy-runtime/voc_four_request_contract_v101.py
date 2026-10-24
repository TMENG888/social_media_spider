"""Mechanical one-unit response constraints, not a semantic acceptance gate."""
import copy
from collections import Counter
from voc_four_literal_recovery_v101 import repair_schema

def current_keys(item,catalog):
 keys=[e['source_key'] for e in catalog if e['unit_id']==item['unit_id']]
 if not keys:raise ValueError('Requested unit has no own literal evidence keys')
 return list(dict.fromkeys(keys))

def single_unit_schema(items,catalog,fields,references,taxonomy,project_slots=False):
 if len(items)!=1:raise ValueError('Exactly one unfinished unit per request')
 schema=repair_schema(items,catalog,fields,references)
 own=current_keys(items[0],catalog);ids=[t['tag_id'] for t in taxonomy]
 if not ids or len(ids)!=len(set(ids)):raise ValueError('Full dictionary IDs must be unique')
 array=schema['properties']['units'];array['minItems']=1;array['maxItems']=1
 unit=array['items']['properties'];tag=unit['views']['items']['properties']['labels']['items']['properties']
 # Replace leaves: the legacy schema shares dicts with context references.
 tag['attribute_keys']['items']={'type':'string','enum':own}
 tag['attribute_keys']['minItems']=1
 tag['tag_id']={'type':'string','enum':ids}
 unit['facts']['items']['properties']['source_key']={'type':'string','enum':own}
 unit['facts']['items']['properties']['tag_ids']['items']={'type':'string','enum':ids}
 # This Qwen gateway rejects uniqueItems on arrays. Duplicate labels remain
 # mechanically checked locally and are repaired with exact ID feedback.
 if project_slots:
  template=unit['views']['items'];properties={}
  for pid in template['properties']['project_id']['enum']:
   view=copy.deepcopy(template);view['properties']['project_id']={'type':'string','enum':[pid]};properties[pid]=view
  unit['views']={'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
 return schema

def exact_repair_feedback(response,item,catalog,problems,references=None):
 """Expose exact duplicate/missing keys. Qwen decides how to resolve them."""
 own=set(current_keys(item,catalog));output=set();fact_tags=set();duplicate={};wrong_attr=[];wrong_facts=[];wrong_identity=[]
 project_counts=Counter(v['project_id'] for v in response.get('views',[]));project_tag_counts={}
 allowed_refs={(r['context_source'],r['quote']) for r in references or [] if r.get('context_source')}
 for view in response.get('views',[]):
  counts=project_tag_counts.setdefault(view['project_id'],Counter());counts.update(t['tag_id'] for t in view['labels'])
  repeated=[tid for tid,n in counts.items() if n>1]
  if repeated:duplicate[view['project_id']]=repeated
  for tag in view['labels']:
   output.add(tag['tag_id'])
   for key in tag['attribute_keys']:
    if key not in own:wrong_attr.append({'project_id':view['project_id'],'tag_id':tag['tag_id'],'source_key':key})
   identity=tag.get('project_identity',{})
   if allowed_refs and (identity.get('context_source'),identity.get('quote')) not in allowed_refs:
    wrong_identity.append({'project_id':view['project_id'],'tag_id':tag['tag_id'],'context_source':identity.get('context_source'),'quote':identity.get('quote')})
 for fact in response.get('facts',[]):
  fact_tags.update(fact['tag_ids'])
  if fact['source_key'] not in own:wrong_facts.append(fact['source_key'])
 return {'errors':list(problems),'unit_id':item['unit_id'],'allowed_attribute_and_fact_keys':sorted(own),
  'duplicate_project_view_counts':{pid:n for pid,n in project_counts.items() if n>1},
  'duplicate_tag_ids_by_project':duplicate,'cross_unit_attribute_keys':wrong_attr,'cross_unit_fact_keys':wrong_facts,
  'fact_tags_missing_from_output':sorted(fact_tags-output),'output_tags_missing_fact_link':sorted(output-fact_tags),
  'unlocatable_project_identities':wrong_identity,'literal_identity_field_quote_options':references or [],
  'repair_contract':'同项目同tag_id仅返回一条，可在这一条合并多个当前片证据及对象理由；不得借其它片属性事实。'
   'facts有tag_id须在对应有据项目labels输出；若当前片确无四项目适用标签，views=[]且事实tag_ids=[]，用no_label_reason解释。'
   '由Qwen据原文决定适用/不适用，不得为通过字段检查制造标签。','previous_response_to_repair':copy.deepcopy(response)}

def repair_system(base,feedback):
 """Promote only mechanical contradictions, not a preferred semantic verdict."""
 if not feedback:return base
 import json
 compact={uid:{k:v for k,v in detail.items() if k!='previous_response_to_repair'} if isinstance(detail,dict) else detail for uid,detail in feedback.items()}
 return (base+'\n当前是未保存字段的机械修复，不是沿用上一轮答案。最终views.labels中的tag_id集合必须与facts中tag_ids并集完全相等。'
  '尤其不能一面给views=[]，一面给facts非空tag_ids。若有适用标签，由你根据原文补齐正确项目的labels及证据；'
  '若确无适用标签，由你明确返回views=[]、facts.tag_ids=[]以及具体no_label_reason。两种结论均允许，不预设哪种。'
  'views中每个project_id只能出现一次：同一项目的所有标签必须合并到这一个view中，不得因合并丢掉有据标签。'
  '同项目同tag_id只返回一次并合并本片证据。不得复制上一轮仍有结构矛盾的响应。当前精确错误：'+json.dumps(compact,ensure_ascii=False))
