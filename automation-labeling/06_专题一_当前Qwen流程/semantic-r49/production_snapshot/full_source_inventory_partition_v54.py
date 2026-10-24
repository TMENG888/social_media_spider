"""Staged factual-object inventory, then whole-source proposal and fresh audit.

The same underlying runner owns the global semaphore and all retry accounting.
Inventory guesses are explicitly non-authoritative and never delivery prose.
"""
import full_source_key_partition_v53 as previous
import source_object_fact_ledger_v54 as inventory
import inventory_continuity_candidates_v55 as continuity

CONTEXT='''\npreliminary_object_inventory是上一独立信息提取的待审线索，不是事实权威。
先根据其实际原文键回读source_text，纠正它的对象/承接误判，不照抄对象描述。
range判断与完整主题审核须区分具体物理系统与叙述形式：新问答环节不证明新对象。
若目录指出restatement/correction，必须回读原始方案及当前重述，核是否同一实际机制。
纯附和/短情绪没有配置不等于换对象；可桥接的前提仍是全文未转换具体系统。
不同系统即使同一个节目、同一项目、同一质量标签也不得合并。
任何最终批准仍按原文独立决定，目录置信度不能代替当前组置信度。'''

class InventoryRunner:
    def __init__(self,runner,ledger):
        self.runner=runner;self.ledger=ledger
        self.supports_response_schema=getattr(runner,'supports_response_schema',False)
    def call(self,system,payload,doc,phase,**kwargs):
        return self.runner.call(system+CONTEXT,dict(payload,preliminary_object_inventory=self.ledger),doc,
                                phase+'-事实对象目录上下文-v11.54',**kwargs)

def review(doc,plan,segments,runner):
    if doc.get('kind')!='文章' or len(plan['units'])<2:return plan,[],[],[]
    entries=previous.ranges.previous.previous.previous.grouping.catalog(doc,plan,segments)
    ledger,audit,calls,issues=inventory.review(doc,entries,runner)
    if issues:return plan,audit,calls,issues
    out,group_audit,group_calls,errors=previous.review(doc,plan,segments,InventoryRunner(runner,ledger))
    audit+=group_audit;calls+=group_calls
    if not errors:
        out,restatement_audit,restatement_calls,errors=continuity.review(doc,plan,segments,entries,ledger,out,runner)
        audit+=restatement_audit;calls+=restatement_calls
    if not errors:out['source_object_inventory_audit']=audit
    return out,audit,calls,errors
