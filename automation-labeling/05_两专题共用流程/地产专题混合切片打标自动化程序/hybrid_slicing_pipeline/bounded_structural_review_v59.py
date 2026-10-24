"""One structural repair only. Valid uncertainty/rejection is final.

Use the supplied shared ApiRunner; never create a second concurrency limiter,
read secrets, change raw replies, or substitute default confidence values.
"""
import copy
from structured_response_validation_v58 import issues as schema_issues

def review(system,payload,schema,doc,phase,runner):
    calls=[];audit=[];current=copy.deepcopy(payload)
    for attempt in range(2):
        raw,metrics=runner.call(system,current,doc,phase if not attempt else phase+'-结构恢复',response_schema=schema)
        calls.append(metrics)
        if metrics.get('status')!='success':
            errors=['独立核验API未成功']
            audit.append({'raw_response':raw,'protocol_issues':errors})
            return None,calls,audit,errors
        errors=schema_issues(raw,schema)
        audit.append({'raw_response':copy.deepcopy(raw),'protocol_issues':errors})
        if not errors:return raw,calls,audit,[]
        current=dict(payload,previous_response=raw,protocol_issues=errors,
            repair_instruction='只修实际结构违规，重新读原文给规定JSON；允许拒绝和低置信度，不默认补高置信度，不输出过程思考。')
    return None,calls,audit,errors
