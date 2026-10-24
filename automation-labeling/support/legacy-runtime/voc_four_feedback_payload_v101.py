"""Remove old answer templates only after Qwen explicitly rejects project binding."""
import copy


def without_rejected_answer_templates(payload):
 out=copy.deepcopy(payload)
 out.pop('prior_rows_not_gold',None)
 failed=out.get('failed_fields_only')
 if isinstance(failed,dict):
  for detail in failed.values():
   if isinstance(detail,dict):detail.pop('previous_response_to_repair',None)
 out['repair_input_policy']='原失败答案及历史标签不是本轮输出模板；仅按完整原文、全部目录和Qwen自身补证理由重新完成当前缺失单元。'
 return out
