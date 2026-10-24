"""Focused physical-object boundary review and strict definition binding."""
import copy
import delivery_v71 as current
import focused_object_boundary_v72 as objects

VERSION = 'delivery-v11.72-whole-context-focused-object-boundaries-20261010'
pipeline = current.pipeline

BINDING_NOTE = '''
先识别名词实际指的物理设施，而不是用复合名称中的某个词代替设施。
例如“机场高速”是道路名称，单提这个路名不证明周边机场的位置、名称或实际机场通行情况；
不能只因为名字含机场就认同机场配套标签。“高速”也不等于具体高速入口。
设施的临近道路不能替代设施本体；请核对完整标签对象而不是只看重合词。
对unsupported也必须填写actual_object和actual_property的非空说明，
例如“原文对象是道路，未明确机场对象”“原文没有该标签要求的属性”。
非空说明不等于支持，不填虚构证据。示例中的可选数量无需全部出现，路径对象必须有据。
'''


def review(doc, old_plan, old_segments, runner, parse_partition):
    plan, segments, audit, calls, errors = current.review(doc, old_plan, old_segments, runner, parse_partition)
    if errors:
        return plan, segments, audit, calls, errors
    updated, ss, aa, cc, issues = objects.review(doc, plan, segments, runner, parse_partition)
    audit += aa
    calls += cc
    if issues:
        return plan, segments, audit, calls, issues
    updated['full_source_global_boundary_v70'] = copy.deepcopy(audit)
    return updated, ss, audit, calls, []


def activate():
    current.activate()
    pipeline.final_boundary.review = review
    pipeline.binding.SYSTEM += BINDING_NOTE
    pipeline.previous.VERSION = VERSION
    pipeline.previous.IMPLEMENTATION_FILES = list(dict.fromkeys(
        pipeline.previous.IMPLEMENTATION_FILES + ['delivery_v72.py', 'focused_object_boundary_v72.py']))


if __name__ == '__main__':
    activate()
    pipeline.previous.main()
