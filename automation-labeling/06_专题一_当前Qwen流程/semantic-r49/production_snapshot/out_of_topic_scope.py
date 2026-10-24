"""Resolve agreeing content types by the explicit topic contract, not keywords.

Two independent source-grounded reviews may agree on project_environment yet
mistakenly call it relevant to topic one. Topic one delivers product facts only.
Do not turn a missing/malformed review or a mixed product/environment fact set
into exclusion. This is not a source splitter or a label selector.
"""
T1='全国地产设计产品力监测'
T2='北京臻澐项目口碑'
ALLOWED={T1:{'product_fact','quality_defect'},
         T2:{'product_fact','quality_defect','project_environment','opinion','customer_fact'}}
KINDS=set().union(*ALLOWED.values())


def confirmed_outside(scope,review,legal_ids,topic):
    if topic not in ALLOWED or not isinstance(scope,dict) or not isinstance(review,dict):
        return False
    kind=scope.get('content_kind')
    if not isinstance(kind,str) or kind not in KINDS or kind in ALLOWED[topic]:return False
    confidence=scope.get('confidence')
    if type(confidence) not in (int,float) or not .9<=confidence<=1:return False
    if review.get('exclude') is not False:return False
    facts=review.get('positive_facts')
    if not isinstance(facts,list) or not facts:return False
    for fact in facts:
        # Different independently grounded non-product types can coexist.
        # Never exclude if even one item is in-scope or unknown.
        if (not isinstance(fact,dict) or fact.get('kind') not in KINDS
                or fact.get('kind') in ALLOWED[topic]):return False
        ids=fact.get('evidence_ids');confidence=fact.get('confidence')
        if not isinstance(ids,list) or not ids or any(type(i) is not int or i not in legal_ids for i in ids):return False
        if len(set(ids))!=len(ids):return False
        if type(confidence) not in (int,float) or not .9<=confidence<=1:return False
        if any(not isinstance(fact.get(k),str) or not fact[k].strip() for k in ('fact','why')):return False
    return True
