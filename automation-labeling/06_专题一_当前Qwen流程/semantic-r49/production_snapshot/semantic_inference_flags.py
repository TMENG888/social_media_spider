"""Generic audit triggers, not automatic semantic labels or hardcoded gold."""
import re
from additional_object_scope_evidence import scope_issue
from quantity_reason_consistency import issue as quantity_issue
from definition_reason_inference_v50 import assumption_reason as affirmative_inference_reason


def assumption_reason(reason):
    return affirmative_inference_reason(reason)


def unsupported_scope(tag, quote, reason, object_context=''):
    """Conservative veto on a wrong measuring object, not keyword auto-tagging.

    A supported-looking model explanation must not override literal scope.
    Returns a pending-review reason; it does not assign replacement labels.
    """
    quote=str(quote or '');reason=str(reason or '')
    additional=scope_issue(tag,quote,reason)
    if additional:
        return additional
    quantity=quantity_issue(tag,quote,reason)
    if quantity:
        return quantity
    if assumption_reason(reason):
        return '支持理由依赖行业惯例或推断，原文未唯一明示对象属性'
    room=tag.get('l3');attribute=tag.get('l4')
    if room=='别墅' and '双拼户型' in quote:
        if not re.search(r'别墅|双拼住宅|联排|独栋|叠拼|排屋|合院',quote+' '+str(object_context or '')):
            return '双拼户型可能是双套合并格局，未明确别墅住宅业态；不因字典例词双拼直接确认物业类型'
    if '大高' in {tag.get('emphasis'),room,attribute,tag.get('l5')}:
        if '大平层' in quote and not re.search(r'大高(?:层)?|超高层|高层住宅|建筑高度|楼高|\d+\s*层',quote):
            return '大平层描述住宅平面形态，不支持大高建筑高度类型；缺少高度或楼层对象证据'
    if attribute in {'外立面风格','外立面性能'}:
        if not re.search(r'外立面|外墙|幕墙|外窗|建筑立面|建筑外观|建筑风格',quote+' '+str(object_context or '')):
            if re.search(r'园林|景观|花园|室内|装修|装饰|中式|风格|静音|静界|隔音|降噪',quote):
                return '证据对象是园林或室内配置，未明确外立面对象；不把中式或静音字词跨对象标注'
    if tag.get('l1')=='客户' and tag.get('l3')=='购房关注点':
        generic=re.search(r'适合.{0,25}(?:家庭|客群|人群)|客群(?:跨度|覆盖|统一|构成)|从首改到终改|如果你|对于.{0,20}家庭',quote)
        decision=re.search(r'我(?:们)?(?:想|在|正|最近|考虑|看|选|买|纠结|觉得|关注)|本人|我们家|我家|您问|\?|？',quote)
        if generic and not decision:
            return '第三方描述目标客群或提供条件式推荐，未自述本人购房关注；不将营销适配性当客户画像'
        if re.search(r'当前讨论|当前(?:分析|介绍)(?:的)?对象|本文介绍|文章(?:描述|介绍)|是.{0,8}讨论.{0,8}对象',reason):
            if not re.search(r'本人|自述|我(?:们)?|询问|提问|个人(?:关注|选择|纠结)',quote+' '+reason):
                return '仅凭文章讨论对象或出现项目名推导本人关注，缺少客户实际选择/关注行为证据'
    if attribute=='标准户型' and re.search(r'四室贯通|客餐厨阳台',quote):
        if not re.search(r'(?:\d+|[一二两三四五六七八九十]+)\s*(?:房|居|卧|厅|卫)',quote):
            return '客餐厨阳台四功能空间贯通不是四居卧室户型，缺少房厅卫格局证据'
    if room=='主卧' and attribute=='窗' and re.search(r'(?:主卫|卫生间|浴室).{0,8}窗|窗.{0,5}主卫',quote):
        bedroom_quote=re.sub(r'(?:转角窗|飘窗|落地窗|窗户?)\s*主卫','主卫',quote)
        if not re.search(r'主卧[^，。；]{0,10}(?:转角窗|飘窗|落地窗|窗户)|(?:转角窗|飘窗|落地窗).{0,5}主卧',bedroom_quote):
            return '窗的证据对象是主卫/卫生间，不是主卧；不把配套房间属性转给主卧'
    if attribute=='衣柜' and '衣帽间' in quote and not re.search(r'衣柜|柜体|柜门|收纳柜',quote):
        return '衣帽间空间不等于已配置衣柜，缺少柜体证据'
    if room=='家政间' and attribute=='数量':
        if not re.search(r'(?:\d+|[一二两三四五六七八九十]+)\s*(?:个|间|套)[^，。；]{0,8}家政|家政[^，。；]{0,10}(?:数量|共|有|为|设)[^，。；]{0,3}(?:\d+|[一二两三四五六七八九十]+)\s*(?:个|间|套)',quote):
            return '家政空间存在不等于明确计数一间，缺少原文计数证据'
    if tag.get('l1')=='客户' and attribute=='地段位置' and re.search(r'体育场|体育馆|泳池|健身',quote):
        if not re.search(r'地段|区位|位置|区域|附近|距离|离.{0,8}(?:远|近)',quote):
            return '仅休闲设施信息提问，未表达地段位置关注，不能把设施属性扩大为区位属性'
    if room=='通用' and attribute=='面宽' and re.search(r'(?:宽厅|客厅|餐厅|卧室)',quote):
        if not re.search(r'(?:户型|套内|整套|整体).{0,10}(?:面宽|开间)',quote):
            return '证据是单个房间尺寸，不能作为整体户型面宽'
    if attribute=='横厅/竖厅' or room=='客厅' and attribute=='格局':
        if re.search(r'LDKB|宽厅',quote,re.I) and not re.search(r'横厅|竖厅|偏厅|边厅',quote):
            return 'LDKB一体化或宽厅未明确横厅/竖厅，不能由行业惯例补足'
    if tag.get('l3')=='精装质量' and re.search(r'豪装|精装交付',quote):
        if not re.search(r'检测|验收|裂|渗|漏|空鼓|工艺|施工|误差|平整|合格|质量',quote):
            return '交付档次宣传未描述质量做法、检测或质量表现'
    return None


INSTRUCTION='''只接受原文明示或可唯一消歧的对象属性，不按行业惯例补事实。
南向四面宽未说明哪些房间，不能自动分配客厅或主卧朝向；宽厅/LDKB一体化不自动证明横厅。
主卫窗不能当主卧窗；衣帽间空间不自动证明已经装衣柜；双步入衣帽间不能擅自解释成一个。
专属家政套房仅说明存在，不自行补数量1；豪装交付不能单凭豪装二字证明工艺质量表现。
客餐厨阳台“四室贯通”是四功能空间连接，不等于四居/四卧，不能据此填写标准房厅卫户型。
不要将项目档次套给板块档次，不将房屋层高自动当成土地规划条件；保留原文数字，不拆猜黏连数字。
原文口语“一关键”可为第一点等转录内容，不能无据变成人名或地点。
对有明确对象数量(一个/两间)、朝向、房间尺寸的事实可支持；否则ambiguous或unsupported并解释。'''
