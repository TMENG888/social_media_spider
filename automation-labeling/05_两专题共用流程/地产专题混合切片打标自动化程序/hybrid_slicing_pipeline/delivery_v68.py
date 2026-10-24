"""Independently review full-source semantic boundaries before tagging."""
import copy
import delivery_v67 as current

VERSION = 'delivery-v11.68-independent-full-source-boundary-review-20261010'
pipeline = current.pipeline

REVIEW_NOTE = '''
这是独立的边界审核，proposed_boundaries只是待审提案，不能默认照抄。
从全文判断每个边界前后的实际对象是否转换：参数与紧接说明、结论、用途解释
属于同一对象时应一并保留，不能以“优势解释”“价值总结”虚构新对象。
反过来，一个段落先介绍园林再介绍会所，是物理对象转换，不能被段落标题掩盖。
逐个说明最终保留边界的真实对象变化；theme/why不能仅是编辑措辞或解释性转述。
全文的重复案名、营销标题也不是对象转换。若独立属性轴比较确有完整主题变化，
可以另片，但完整主题内参数与解释不能拆开。无关内容仍覆盖，收录另行审核。
输出完整替代方案，而不是修改意见。不预设数量，不把非连续对象拼接。
定位短语不是摘要，最多24字；例如长句“简单说：海晏的户型更撑场面...”
只需原样填写“简单说：”，不把两项目的整句结论都写入start_phrase。
起点属于哪个目录条目就选哪个source_key；不得让短语跨条目，也不改写引文。
'''


def boundary_call(system, payload, schema, doc, phase, runner):
    raw, calls, audit, errors = current.boundary_call(system, payload, schema, doc, phase, runner)
    if raw is None:
        return raw, calls, audit, errors
    request = copy.deepcopy(payload)
    request['proposed_boundaries'] = raw
    request['proposal_protocol_issues'] = errors
    reviewed, more, checks, issues = current.boundary_call(
        system + REVIEW_NOTE, request, schema, doc,
        '完整对象边界独立审核-v11.68', runner)
    return reviewed, calls + more, audit + checks, issues


def activate():
    current.activate()
    current.current.current.boundaries.bounded = boundary_call
    pipeline.previous.VERSION = VERSION
    pipeline.previous.IMPLEMENTATION_FILES = list(dict.fromkeys(
        pipeline.previous.IMPLEMENTATION_FILES + ['delivery_v68.py']))


if __name__ == '__main__':
    activate()
    pipeline.previous.main()
