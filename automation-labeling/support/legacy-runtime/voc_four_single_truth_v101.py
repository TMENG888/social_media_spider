"""Single-decision response adapter for missing Qwen stages only.

Qwen labels remain the sole decisions. The program joins their explicit evidence
keys to a complete Qwen-reviewed fact inventory; it never infers another label.
No existing independent facts verdict may be overwritten by this adapter.
"""
from voc_four_request_contract_v101 import single_unit_schema,current_keys

PHASE='专题二单切片单一裁决与原文项目引文-v101-完整输出'
INSTRUCTION='''本次仅修复未成功保存的切片。所有标签裁决只在views各项目的labels中输出一次，仍检查提供的完整标签目录。
views是四项目固定键；不适用项目的labels/expressions/emotions为空数组，summary空串。
fact_review必须逐一包含当前片全部真实证据键，各键写一句已核查结果：已由哪些事实描述覆盖，或为什么不适用当前四项目标签。
不要输出facts或第二份tag_ids。程序只把你明确输出的labels.attribute_keys关联回相同证据键，生成追溯表，不会替你新增标签。
项目、标签、证据和摘要仍由你按原文判断。没有适用标签可以全部留空，但每条证据都必须有明确核查理由。
不能为通过合同制造标签，也不能因结构修复丢掉有据标签。
literal_project_identity_options/literal_project_reference_options仅为原文复制参考，不是项目映射、封闭别名表或必选引文。
项目归属由你据原文和上下文判断。project_identity.quote可以引用实际原文中的简称、异体字、错别字或上下文指代，说明它为何属于所选项目。
不得因参考表缺少该写法而借用另一个项目名称作证。quote必须是declared_identity_contexts中对应context_source的非空逐字子串，不得改字、拼接或杜撰。
上下文无法支持归属时据实不标，不得为填字段制造项目关联。'''

def response_schema(items,catalog,fields,references,taxonomy,contexts=None):
 schema=single_unit_schema(items,catalog,fields,references,taxonomy,project_slots=True)
 unit=schema['properties']['units']['items'];props=unit['properties'];props.pop('facts')
 props['fact_review']={'type':'object','properties':{key:{'type':'string','minLength':1} for key in current_keys(items[0],catalog)},
  'required':current_keys(items[0],catalog),'additionalProperties':False}
 unit['required']=[key for key in unit['required'] if key!='facts']+['fact_review']
 # Replace leaves rather than mutate shared legacy text dictionaries. Only
 # transport constraints change; the four identities and full tag set remain.
 locations=[key for key,value in (contexts or {}).items() if isinstance(value,str) and value]
 for view in props['views']['properties'].values():
  identity=view['properties']['labels']['items']['properties']['project_identity']['properties']
  identity['quote']={'type':'string','minLength':1}
  identity['context_source']={'type':'string','enum':locations or ['source','title','parent','parent_title']}
 return schema

def request_system(base,feedback):
 import json
 # Keep the signed base policy unchanged on disk, but replace its obsolete
 # transport-field instruction for this explicitly versioned request contract.
 old='facts按当前片证据编号记录事实及其适用tag_ids，无标签也须给no_label_reason；不要逐条列580个未命中字典项。'
 base=base.replace(old,'fact_review逐一核查当前片全部证据；标签只在views.labels输出，不另列facts/tag_ids；不要逐条列580个未命中字典项。')
 compact={uid:{k:v for k,v in detail.items() if k!='previous_response_to_repair'} if isinstance(detail,dict) else detail for uid,detail in feedback.items()}
 return base+'\n'+INSTRUCTION+('\n当前需由Qwen纠正的机械字段错误：'+json.dumps(compact,ensure_ascii=False) if feedback else '')

def repair_feedback(response,raw,item,catalog,problems,references,contexts=None):
 from voc_four_request_contract_v101 import exact_repair_feedback
 # A valid literal quote must never be called unlocatable merely because
 # it is absent from the optional alias-copy reference list.
 out=exact_repair_feedback(response,item,catalog,problems,[])
 wrong=[]
 for view in response.get('views',[]):
  for tag in view['labels']:
   identity=tag.get('project_identity',{});field=identity.get('context_source');quote=identity.get('quote')
   if contexts is not None and (not isinstance(quote,str) or not quote or field not in contexts or quote not in contexts[field]):
    wrong.append({'project_id':view['project_id'],'tag_id':tag['tag_id'],'context_source':field,'quote':quote})
 out['unlocatable_project_identities']=wrong
 out.pop('literal_identity_field_quote_options',None)
 out['optional_literal_copy_references_not_project_mapping']=references or []
 out['available_identity_context_fields']=[key for key,value in (contexts or {}).items() if value]
 out['repair_contract']=INSTRUCTION
 out['previous_response_to_repair']=raw
 return out

def linkage_errors(unit,item,catalog):
 """Only the new contract requires a complete review-key/label-key join."""
 if not unit.get('fact_linkage_derived_from_explicit_qwen_labels'):return []
 review=unit.get('qwen_fact_review');own=current_keys(item,catalog)
 if not isinstance(review,dict) or set(review)!=set(own) or any(not isinstance(x,str) or not x.strip() for x in review.values()):
  return ['单一裁决缺逐证据Qwen核查理由']
 raw={k:v for k,v in unit.items() if k not in ('facts','qwen_fact_review','fact_linkage_derived_from_explicit_qwen_labels')}
 raw['fact_review']=review
 try:expected=derive_unit(raw)
 except (KeyError,TypeError,ValueError):return ['单一裁决证据关联无效']
 return [] if unit['facts']==expected['facts'] else ['单一裁决关联不等于Qwen明确标签证据连接']

def derive_unit(raw):
 """Lossless evidence-key join only; no old independent verdict is discarded."""
 import voc_four_projects_v101 as p
 if 'fact_review' not in raw:return p.normalize_unit(raw)
 if 'facts' in raw:raise ValueError('Never overwrite independent model fact verdicts')
 result=p.normalize_unit(raw);review=result.pop('fact_review')
 if not isinstance(review,dict) or not review or any(not isinstance(reason,str) or not reason.strip() for reason in review.values()):raise ValueError('Every fact needs an explicit Qwen review reason')
 links={key:[] for key in review}
 for view in result['views']:
  for label in view['labels']:
   for key in label['attribute_keys']:
    if key not in links:raise ValueError('Label evidence is outside reviewed own fact inventory')
    links[key].append(label['tag_id'])
 result['facts']=[{'source_key':key,'tag_ids':list(dict.fromkeys(links[key])),
  'no_label_reason':'' if links[key] else reason} for key,reason in review.items()]
 result['fact_linkage_derived_from_explicit_qwen_labels']=True
 result['qwen_fact_review']=review
 return result
