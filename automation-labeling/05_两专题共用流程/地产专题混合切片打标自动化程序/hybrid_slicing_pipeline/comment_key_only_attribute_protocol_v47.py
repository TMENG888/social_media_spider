"""Program-owned attribute evidence; model judges semantics and selects keys.

No retrofitting legacy fabricated quotation responses. This protocol explicitly
does not ask the model to author attribute quotations.
"""
import copy
import re
import comment_binding_schema_v44 as previous


SYSTEM='''只输出JSON。独立核验当前唯一prose_catalog文本是否由完整source_text评论支持，不借父文章事实。
source_evidence_catalog键和turn_id属于程序，原文标题决定发言者；同昵称后续轮次不证明相同对象。
逐项核对象、属性、发言者、比较关系、程度、状态和模态，不只判断是否有相关词。
一个目标命题中任一不支持就unsupported；指代不唯一uncertain，不向最近项目名移植。
原文“二选一也许较好”且同轮前句“没听过”，摘要须保留未体验及相对不确定性质；“倾向”也不能漏未体验。
允许忠实同义转写：觉得/认为、家里/家中、反问听不到的说法/质疑听不到的说法，不能只因换词拒绝。
不把反问改成真诚询问原因。“声音可闻但不影响生活”不得改成严重影响；不能漏掉场景和程度。
片段核验只审实际目标，不要求每片包含其他命题。全评论主要事实覆盖另有独立审核。
绑定只选实际原文键，属性全文由程序原样回填，禁止返回attribute_quote或assertion_quote。
object_quote为当前目标文本里的对象名词；source_object_quote是包含在object_source_key原文的对应逐字名词。
同一目标有多个对象或多个事实，分别绑定。属性证据包含整个原文目录片段，须先读原文判断支持关系，不能只依赖键合法性。
名词对象不能带共享动作：例如“去南外环和新河路”，对象为南外环、新河路，不写“去新河路”。
只有目标本身未明示具体对象才可泛指null；“该地/这里/此处”没有具体名时可泛指，不能伪造项目。
具体发言者、项目或地块名必须有对应对象证据。不得把明确对象伪装泛指规避核验。
同一轮对象名可承接后一句属性；不同轮未重述对象则无可靠回复关系，不能绑定该具体对象。
返回唯一结构：{"checks":[{"prose_key":"唯一实际目标键","status":"supported/unsupported/uncertain",
"source_keys":["实际原文键"],"object_binding_supported":true,"relation_supported":true,
"modality_preserved":true,"qualifiers_preserved":true,"why":"简短最终支持依据或实际错误","confidence":0.95}],
"object_bindings":[{"prose_key":"同一实际目标键","object_quote":null,"source_object_quote":null,
"object_source_key":null,"attribute_source_key":"实际属性原文键"}]}。
两个根键都须返回。泛指三个对象字段均null；明确对象三个对象字段须有真实来源。generic_or_unresolved由程序按对象是否null确定，禁止模型返回此冗余字段。
两个小区位于机场两侧不证明都受同程度噪音影响；项目名出现在相对位置说明里，不代表它有相同的听感证据。逐对象核各自属性证据，不借另一个项目或其他轮次的声音评价。
不输出思考过程、改写目标、标签或摘要；status与why必须一致。不以高信心或前次通过代替证据。
'''


def verify(fragment,entries,response):
    bindings=response.get('object_bindings') if isinstance(response,dict) else None
    lookup={e['source_key']:e for e in entries}
    if not isinstance(bindings,list) or not bindings:
        return False,[{'accepted':False,'issues':['键选属性协议缺少对象绑定']}]
    materialized=copy.deepcopy(response)
    for binding in materialized['object_bindings']:
        if not isinstance(binding,dict):return False,[{'accepted':False,'issues':['对象绑定结构无效']}]
        if 'attribute_quote' in binding or 'assertion_quote' in binding:
            return False,[{'accepted':False,'issues':['新协议禁止模型生成属性/目标引文，旧引文不可静默修正']}]
        if 'generic_or_unresolved' in binding:
            return False,[{'accepted':False,'issues':['新版对象空值协议禁止模型返回冗余泛指布尔，不静默修正旧响应']}]
        key=binding.get('attribute_source_key')
        if not isinstance(key,str) or key not in lookup:
            return False,[{'accepted':False,'issues':['属性键不在实际原文目录']}]
        binding['attribute_quote']=lookup[key]['text']
        binding['generic_or_unresolved']=binding.get('object_quote') is None
        if (binding.get('object_quote') is not None and re.search(r'均|两者|都受|都受到',fragment['text'])
                and re.search(r'噪|吵|驱鸟|飞机|声音',fragment['text'])
                and not re.search(r'驱鸟|噪|吵|声音|听|聋|轰鸣|刺耳|响|声',lookup[key]['text'])):
            return False,[{'accepted':False,'issues':['共同噪音影响命题的具体对象仅绑定位置/名称原文，没有该对象的听感/影响证据；不能由机场两侧位置推导同样噪音']}]
    okay,audit=previous.verify(fragment,entries,materialized)
    for item in audit:
        item['attribute_evidence_owner']='program-literal-source-key'
        item['raw_key_only_response']=copy.deepcopy(response)
    return okay,audit
