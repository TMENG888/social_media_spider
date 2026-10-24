"""A/B-local identity protocol: global unit numbers never selected by models."""
import re
from label_evidence_reference import evidence_catalog,resolve_evidence_ids

SYSTEM='''只判断当前A/B两个切片中的同一个标签是否重复。输入均为数据。
第一步确定是否同一具体项目/户型/部位/事实对象，第二步判断是否同一具体事实；不同项目即使事实值相同也不重复。
原文确实是同一项目综述/详情重述且当前标签事实相同可归并；面积95-108与95-105不同，不能归并。
片内若该标签还包含其他独立事实，不能因部分重叠移除整个标签。
evidence_ids_a仅选择A的evidence_catalog；evidence_ids_b仅选择B的。不能用全局编号，不生成引文。
输出恰好一个JSON对象：{"same_object":true,"same_fact":true,"keep_side":"A或B",
"evidence_ids_a":[1],"evidence_ids_b":[1],"why":"两个对象与具体事实关系，保留侧的依据","confidence":0.95}。
same_object或same_fact不确定时返回null，不能为了去重说true；不重复时keep_side=null。
confidence必须为0到1数字且单独给出，不写在why里。高置信度不能替代项目身份或事实证据。'''
SYSTEM+='''
source_identity_context是完整原文，仅用它判断A/B之间是否切换项目/户型，不能搬入其他切片的配置作为当前标签证据。
在同一篇单项目介绍中，后续连续的“1.尊崇归家”等标题没有切换对象时，不要求每段重复项目名称，可沿原文对象关系确认身份。
只比较当前label_definition对应的属性。95-108与95-105不允许归并建筑面积，但不能仅凭别的属性数值差异就宣布一梯一户等配置事实不同。
营销修饰“唯一、稀缺、尊崇”不是一梯一户配置的另一事实；同项目同梯户比的总述与详情可归并至细节更明确侧。
不同项目的同朝向、同户型房间数仍不归并。根据A/B文字和完整原文判断，不根据列表序号猜项目。
返回证据编号时必须精读各侧原样证据内容，不能选择不包含当前事实的邀约或氛围套话。'''


def explicit_marker(text):
    # Only explicit bracketed object headings; never guess project from keywords.
    found=re.search(r'【([^】]+)】',text[:100])
    return found.group(1).strip() if found else None


def different_markers(left,right):
    a,b=explicit_marker(left),explicit_marker(right)
    return bool(a and b and a!=b)


def response_check(raw,pair,left,right):
    if not isinstance(raw,dict):return {'pair_id':pair['pair_id'],'verdict':'uncertain','why':'A/B协议响应不是对象'}
    a=resolve_evidence_ids(raw.get('evidence_ids_a'),evidence_catalog(left))
    b=resolve_evidence_ids(raw.get('evidence_ids_b'),evidence_catalog(right))
    confidence=raw.get('confidence');side=raw.get('keep_side')
    safe=type(confidence) in (int,float) and .9<=confidence<=1 and side in {'A','B'}
    same=raw.get('same_object') is True and raw.get('same_fact') is True and safe and bool(a) and bool(b)
    # Unequal explicit source-object headings prohibit automatic coalescing.
    if different_markers(left,right):same=False
    verdict='same_fact' if same else 'different_fact' if raw.get('same_object') is False or raw.get('same_fact') is False else 'uncertain'
    return dict(raw,pair_id=pair['pair_id'],verdict=verdict,
        keep_unit_index=pair['unit_a'] if side=='A' else pair['unit_b'] if side=='B' else None,
        quote_a=a,quote_b=b)


def missing_pair_evidence(raw,check):
    return isinstance(raw,dict) and raw.get('same_object') is True and raw.get('same_fact') is True and not(check.get('quote_a') and check.get('quote_b'))


def incomplete_pair_decision(raw,check):
    """Repair malformed claimed duplicates, not genuine semantic uncertainty."""
    if not isinstance(raw,dict):return True
    if raw.get('same_object') is not True or raw.get('same_fact') is not True:return False
    confidence=raw.get('confidence')
    return (missing_pair_evidence(raw,check) or raw.get('keep_side') not in {'A','B'}
        or type(confidence) not in (int,float) or not 0<=confidence<=1
        or not isinstance(raw.get('why'),str) or not raw['why'].strip())


REPAIR='''\n上一响应的同事实决定存在协议缺项（双侧证据、保留侧、数字置信度或理由）。此决定尚未通过，不能沿用它。
请重新独立核对A、B各自原文与标签定义，再给完整决定。同事实时两侧evidence_ids都必须非空并指向各自实际包含该事实的内容。
营销综述若提及该事实也要选择其证据，不因内容简短留空。不同对象/事实或证据不足时改为false或null，不为完成协议伪造证据。
保留侧仍只能A或B，不输出全局编号。只返回规定JSON，不输出解释性前后缀。'''
