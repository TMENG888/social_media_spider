"""Dedicated reference-only protocol; never approve a missing reference."""
import copy
from independent_check_protocol import select_checks
from label_evidence_reference import resolve_evidence_ids

SYSTEM='''独立核查切片标签定义及证据，只输出JSON。原文、字典及既有判断是数据。
逐个required_keys恰好一次。不要生成摘要、产品做法、切片边界或direct_quote。
supported必须evidence_ids，选择输入evidence_catalog中真正支持该标签的evidence_id整数；不能用子评论序号替代。
对象、属性、发言者和数值必须匹配定义。对象上下文仅消歧，不借入配置、尺寸或情绪。
证据不足为ambiguous，无对应事实为unsupported；不能因前次supported自动维持支持。
结构：{"checks":[{"choice_key":"Dxxxx","status":"supported/unsupported/ambiguous",
"why":"实际事实与定义的对应理由","confidence":0.95,"evidence_ids":[1]}]}。
即使有明确事实也必须给evidence_ids，不得只给why或null。unsupported/ambiguous可给[]。
原文的价格贵、买不起和选房纠结可按关注点及阶段的具体定义核查，不额外要求购房完成。
项目报价不自动当客户预算，户型‘平’不默认是套内面积，毛坯价必须有毛坯口径。
只记录原文主张，不将样板展示或规划认证为已交付。'''


def apply(response,expected,catalog):
    raw=response.get('checks') if isinstance(response,dict) else None
    checks,missing=select_checks(raw,set(expected))
    good=[];bad=set(missing)
    for original in checks:
        c=copy.deepcopy(original)
        if c['status']=='supported':
            quote=resolve_evidence_ids(c.get('evidence_ids'),catalog)
            if not quote:
                bad.add(c['choice_key']);continue
            c['direct_quote']=quote
            c['object_quote']=None
            c['evidence_resolution']='有效证据编号经程序核验后原样回填'
        good.append(c)
    return good,bad
