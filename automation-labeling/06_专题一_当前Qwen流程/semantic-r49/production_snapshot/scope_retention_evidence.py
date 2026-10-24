"""Evidence contract for reversing a proposed exclusion; no keyword admission.

Neither a failed exclusion call nor a general mention of real estate proves
there is a valid product/opinion unit. A recovery must identify the actual
in-scope fact. Uncertainty is preserved in audit, not declared irrelevant.
"""


INSTRUCTION = '''本次反查如exclude=false，必须另外给positive_facts，逐项说明本切片内真正的研究事实。
每项结构：{"kind":"product_fact/quality_defect/project_environment/opinion/customer_fact",
"fact":"概括原文明确事实，不补配置或态度","evidence_ids":[1],"why":"该原文如何支持事实及当前专题","confidence":0.95}。
专题一只允许product_fact、quality_defect。品牌故事、工法样板间参观、节目总结或律师取证建议不是产品配置/工艺事实。
专题二另允许项目环境、观点、客户自述。仅提到地产/项目名仍不能证明存在观点或配置。
正例“存水弯水封大于50毫米”具有具体做法；反例“最后一期讲清楚了吗，欢迎评论或参观”没有具体做法。
如无法指出明确事实，返回exclude=null、positive_facts=[]并具体解释不确定，不为了保留内容编造事实。
如明确无关，exclude=true、positive_facts=[]。证据ID只来自当前段目录。'''


def supported_retention(response, legal_ids, product_only):
    if not isinstance(response, dict) or response.get('exclude') is not False:
        return False
    facts = response.get('positive_facts')
    if not isinstance(facts, list) or not facts:
        return False
    allowed = {'product_fact', 'quality_defect'}
    if not product_only:
        allowed |= {'project_environment', 'opinion', 'customer_fact'}
    for fact in facts:
        if not isinstance(fact, dict):continue
        ids = fact.get('evidence_ids')
        confidence = fact.get('confidence')
        grounded = (isinstance(ids, list) and bool(ids)
            and all(type(i) is int and i in legal_ids for i in ids)
            and len(ids) == len(set(ids)))
        if (isinstance(fact.get('kind'), str) and fact['kind'] in allowed and grounded
            and type(confidence) in (int, float) and .9 <= confidence <= 1
            and isinstance(fact.get('fact'), str) and fact['fact'].strip()
            and isinstance(fact.get('why'), str) and fact['why'].strip()):
            return True
    return False
