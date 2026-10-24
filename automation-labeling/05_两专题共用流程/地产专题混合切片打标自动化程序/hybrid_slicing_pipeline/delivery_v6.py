"""Full-document generation + independent full-catalogue coverage audit.

Selection keys are issued by the dictionary, never invented by the model.
Neither lexical recall nor pre-slices restrict the semantic model's choices.
Historical data and responses remain untouched.
"""
from __future__ import annotations
import argparse
import copy
import getpass
import json
import os
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import delivery_v4 as base
import delivery_v5 as legacy
from multilabel_v2 import MARKETING, DIMENSION, clause_spans
from marketing_evidence_scope import factual_scope

VERSION = 'delivery-v6.1-full-catalogue-coverage-platform-id-20261009'
SYSTEM = legacy.SYSTEM.replace(
    '一次完成全文语义切片、多标签、摘要/产品做法、主体归属与诚实自检。没有第二次修复或补标机会，通读到全文末尾。',
    '先通读全文再完成语义切片、多标签、摘要/产品做法、主体归属与诚实自检。不要被宣传开头或首个标签分支限制，通读到全文末尾。'
).replace(
    '输出标签时只返回完整原样的标签强调方向direction；不生成标签ID、编号或一级至五级，程序会精确回填。不创造或改写标签词。',
    '输出每个标签只用label_catalog中程序颁发的choice_key，不输出direction、标签ID、编号或层级。每个key唯一对应标签定义，不按词面乱选。'
).replace('"direction":"字典标签强调方向完整原文"', '"choice_key":"Dxxxx"')
SYSTEM += '''
重要反例：询问“看房要验资吗？300w？”不是本人预算300万；销售账号“内部优惠房源，想要私信”不是本人客户阶段或成交状态。
重要正例：客厅挑高6.1米并可改两层，分别检查客厅尺度与灵活可变空间；会所对象前文已确立、后文茶室棋牌室无对象切换，允许承接上下文，不要求每句重复会所。
设备安装、样板展示、预留管线、交付承诺必须区分；可记录所述配置，但不能把展示或预留写成已交付安装。
同一全文必须考虑全部label_catalog，不能仅选出现字典原词的标签。不同空间尺寸必须保留测量对象，未知不能补。'''

REVIEW_SYSTEM = SYSTEM + '''
当前任务不是确认首轮答案，而是独立全文覆盖审核与纠错。draft只是待审核结果，可能漏标签、错标签或错边界。
先独立读完整source_segments，再逐条检查完整label_catalog每一个choice_key的定义，不受draft的候选范围限制。
补齐所有有证据的标签与事实；修正错标签、摘要、对象、重复/碎片化边界；无关内容有理由排除。评论必须全文一行。
返回完整最终units（不是增量），结构与生成任务相同。另外必须返回coverage对象：
{"supported_keys":["Dxxxx"],"unsupported_keys":["Dxxxx"],
"ambiguous":[{"choice_key":"Dxxxx","reason":"明确说明缺的对象/数值/归属证据"}],
"confidence":0.95,"issues":[]}。
三个集合必须无重复、无交集、无字典外key，并完整覆盖当前label_catalog所有key，禁止省略尾部标签。
supported_keys恰好等于最终units所有标签的key集合。可能相关但证据不足归ambiguous，不能强塞。
每个标签都要直接事实证据及对象上下文编号、why和confidence；每个unit的self_check要检查转写、标签定义、对象和完整性。
首轮排除也必须独立审核，不能因为draft为空就不读原文。coverage是审计轨迹，不是零漏标的保证。
unmatched_information仅放相关但无字典标签、证据不足或仍不能处理的信息；已经补齐的信息不应继续列为遗漏。
不要在supported_keys之外另列未经全文证据支持的“推荐标签”。'''
REVIEW_SYSTEM += '''
如果最终结果删除了draft中已选择的标签，必须额外返回removed_draft_labels数组：
[{"choice_key":"Dxxxx","reason":"说明为何原证据不符合该标签定义，例如测量对象错误/仅验资提问/仅预留未安装"}]。
每一个从全文最终标签集合消失的首轮标签都须解释，不允许仅在unsupported_keys列编号而静默删除。
没有删除则返回空数组。保留同标签但改变证据时，在对应标签why说明证据取舍，并保留其他独立事实。'''


def normalize(value):
    return re.sub(r'[\s·•/\\_\-：:（）()]+', '', str(value or '')).casefold()


def registry(taxonomy, topic):
    # Source tag IDs are internal to the registry, not model-authored path values.
    applicable = [t for t in taxonomy if topic in t['topics']]
    index = {'D'+t['tag_id'].split('-')[-1]:t for t in applicable}
    if len(index) != len(applicable):
        raise ValueError('Duplicate dictionary selection key')
    return index


def catalogue(taxonomy, topic):
    return [{'choice_key':key, '标签强调方向':t['emphasis'], '打标说明':t['instruction'],
             '标签对象路径':[t.get('l'+str(i)) or None for i in range(1,6)]}
            for key,t in registry(taxonomy,topic).items()]


def resolve_selection(selection, index):
    key = selection.get('choice_key')
    if key is not None:
        if not isinstance(key,str) or key not in index:
            return None, '无效字典选择编号：'+str(key)
        return key, '程序颁发固定编号'
    value = normalize(selection.get('direction'))
    if not value:
        return None, '缺少字典选择编号/标签方向'
    exact = [k for k,t in index.items() if normalize(t['emphasis']) == value]
    if len(exact) == 1:
        return exact[0], '唯一规范化标签方向兼容回填'
    aliases = [k for k,t in index.items() if value == normalize(next(
        (t.get('l'+str(i)) for i in range(5,0,-1) if t.get('l'+str(i))), ''))]
    if len(aliases) == 1:
        return aliases[0], '唯一字典末级名称兼容回填'
    return None, '标签名称无唯一字典匹配，禁止猜测：'+str(selection.get('direction'))


def canonicalize(raw, index):
    result = copy.deepcopy(raw)
    if not isinstance(result,dict) or not isinstance(result.get('units'),list):
        return result, ['响应没有units数组']
    global_issues=[]
    for unit in result['units']:
        if not isinstance(unit,dict):
            global_issues.append('单元不是对象');continue
        selections=[]
        issues=list(unit.get('uncertainties') or [])
        for selection in unit.get('labels') or []:
            if not isinstance(selection,dict):
                issues.append('标签选择不是对象');continue
            key,provenance=resolve_selection(selection,index)
            if not key:
                issues.append(provenance);continue
            tag=index[key]
            mapped=dict(selection,choice_key=key,direction=tag['emphasis'],resolution=provenance)
            if selection.get('direction') and normalize(selection['direction']) != normalize(tag['emphasis']):
                issues.append('选择编号与模型标签名称不一致，按编号回填但须审核：'+key)
            selections.append(mapped)
        unit['labels']=selections;unit['uncertainties']=issues
    return result,global_issues


def coverage_check(raw, index):
    issues=[]
    if not isinstance(raw,dict):return ['覆盖审核响应不是对象']
    coverage=raw.get('coverage')
    if not isinstance(coverage,dict):return ['缺少全字典覆盖审核分区']
    supported=coverage.get('supported_keys');unsupported=coverage.get('unsupported_keys');ambiguous=coverage.get('ambiguous')
    if not isinstance(supported,list) or not isinstance(unsupported,list) or not isinstance(ambiguous,list):
        return ['全字典覆盖审核三个分区格式错误']
    if any(not isinstance(x,str) for x in supported+unsupported):return ['覆盖选择编号必须为字符串']
    if any(not isinstance(a,dict) or not isinstance(a.get('choice_key'),str) or not base.useful(a.get('reason')) for a in ambiguous):
        return ['歧义分区缺少选择编号或具体理由']
    ambiguous_keys=[a['choice_key'] for a in ambiguous]
    all_keys=supported+unsupported+ambiguous_keys
    if len(all_keys)!=len(set(all_keys)):issues.append('覆盖分区重复或交叉')
    missing=set(index)-set(all_keys);unknown=set(all_keys)-set(index)
    if missing:issues.append('全字典审核遗漏选择编号：'+','.join(sorted(missing)))
    if unknown:issues.append('全字典审核含非法编号：'+','.join(sorted(unknown)))
    selected=set()
    for unit in raw.get('units') or []:
        if not isinstance(unit,dict):continue
        for a in unit.get('labels') or []:
            if not isinstance(a,dict):continue
            key,_=resolve_selection(a,index)
            if key:selected.add(key)
    if selected!=set(supported):issues.append('审核支持标签与最终单元标签不一致：'+','.join(sorted(selected^set(supported))))
    if not base.confidence(coverage.get('confidence')) or coverage['confidence']<.90:
        issues.append('全文覆盖审核置信度不足0.90或缺失')
    issues.extend(str(x) for x in coverage.get('issues') or [])
    if ambiguous:issues.append('仍有证据/定义歧义标签：'+base.dumps(ambiguous))
    return issues


def selection_keys(raw,index):
    keys=set()
    if not isinstance(raw,dict) or not isinstance(raw.get('units'),list):return keys
    for unit in raw['units']:
        if not isinstance(unit,dict):continue
        for selection in unit.get('labels') or []:
            if not isinstance(selection,dict):continue
            key,_=resolve_selection(selection,index)
            if key:keys.add(key)
    return keys


def removal_check(draft,reviewed,index):
    """Do not silently lose a draft tag during independent semantic correction.

    Explanations are auditable, not proof of correctness; no automatic union of
    both answers, which would reintroduce known false positives.
    """
    removed=selection_keys(draft,index)-selection_keys(reviewed,index)
    reasons=reviewed.get('removed_draft_labels') if isinstance(reviewed,dict) else None
    if reasons is None and not removed:return []
    if not isinstance(reasons,list):return ['审核删除首轮标签但缺少逐标签纠错理由：'+','.join(sorted(removed))]
    issues=[];explained=set()
    for item in reasons:
        if not isinstance(item,dict) or item.get('choice_key') not in index or not base.useful(item.get('reason')):
            issues.append('删除首轮标签的纠错理由结构或编号非法');continue
        key=item['choice_key']
        if key in explained:issues.append('删除理由重复：'+key)
        if key not in removed:issues.append('删除理由与实际标签变化不一致：'+key)
        explained.add(key)
    if removed-explained:issues.append('审核删除首轮标签未说明原因：'+','.join(sorted(removed-explained)))
    return issues


SPACES={'餐厅','客厅','主卧','次卧','厨房','卫生间','书房','玄关','大堂','地下大堂','会所','架空层','阳台','露台','儿童房','卧室'}
ALIASES={'厨房':['厨房','厨电'],'客厅':['客厅','大通厅','宽厅'],'主卧':['主卧','主卧室'],'次卧':['次卧','次卧室']}


def evidence_guard(evidence, tag, context=''):
    """Hard contradictions only; positive semantic support comes from review.

    Comma-aware invitation filtering never erases the neighbouring factual clause.
    Uncertain states are retained but must be sent to manual review.
    """
    text=context+'\n'+evidence if context else evidence
    # Usernames are attribution metadata, not first-person evidence.
    text=re.sub(r'【[^】]*】','',text)
    clauses=[text[a:b] for a,b in clause_spans(text)]
    factual=[factual_scope(c,MARKETING) for c in clauses]
    scoped=''.join(factual)
    if not scoped:return 'rejected','仅营销邀请，无标签事实证据'
    if tag.get('emphasis') in {'毛坯总价','精装总价'}:
        state='毛坯' if tag['emphasis']=='毛坯总价' else '精装'
        if state not in scoped and not (state=='精装' and re.search(r'豪装|全装修|带装修',scoped)):
            return 'rejected','价格未明确对应'+state+'房源，不能按总价推断装修口径'
    if tag['emphasis']=='超高' and not re.search(r'超高层|超高住宅|超高建筑',scoped):
        return 'rejected','高得房率/拓展性不是超高层住宅'
    if tag.get('l4')=='高速入口' and not re.search(r'入口|出入口|收费站|互通|匝道',scoped):
        return 'rejected','邻近高速没有入口事实'
    deepest=next((tag.get('l'+str(i)) for i in range(5,0,-1) if tag.get('l'+str(i))), '')
    obj=tag.get('l3') or ''
    if tag['l1']=='客户':
        if tag.get('l2')=='购房动机' and not re.search(
                r'购房|买房|买(?:这|那个|这个|新房|二手|住宅|房子|在|到)|不买|不能买|换房|换到|选房|选(?:这|那个|这个)|不选|不考虑(?:这|那个|这个)|搬(?:家|到|来)|为了.{0,16}(?:住|上学|通勤)',evidence):
            return 'rejected','仅环境评价或现有体验，没有将其明确关联本人购房/换房选择，不能推成购房动机'
        if deepest in {'总价预算','首付预算','月供预算'} and not re.search(r'我(?:们)?(?:的)?(?:购房)?预算|本人预算|预算(?:是|为|在|约|\d)|我(?:们)?(?:准备|打算|计划).{0,8}(?:买|购)|我(?:们)?(?:能拿出|能付).{0,8}',scoped):
            return 'rejected','提问验资/价格不代表本人明确预算'
        if tag.get('l3')=='居住现状' and deepest=='购房/租房' and not re.search(r'(?:我|我们|本人).{0,10}(?:现在住|目前住|已经买|已买|租住|租房|自住|住在)|目前租住|目前自住',scoped):
            return 'rejected','看房提问不代表本人已购房或租房的居住现状'
        if deepest in {'客户阶段','成交状态','购房/租房'} and re.search(r'优惠房源|优惠政策|内部独家|私信|我发您|想要的打招呼',text):
            return 'rejected','销售宣传不是本人客户阶段/成交/居住现状'
        # No first-person keyword is required. A comment can state its own
        # criticism or living experience without "我". Only the independent
        # speaker/definition review can establish personal attribution; this
        # lexical hard-contradiction guard must not pretend to do that.
    if obj in SPACES:
        terms=ALIASES.get(obj,[obj])
        # Standard floor-plan notation "3房2厅2卫" explicitly gives the
        # bathroom count, but says nothing about its size or guest/master split.
        explicit_bathroom_count=obj=='卫生间' and deepest=='数量' and bool(re.search(r'(?:\d+|[一二两三四五六七八九十]+)\s*卫(?!生)',scoped))
        if not any(term in scoped for term in terms) and not explicit_bathroom_count:return 'rejected','缺少空间对象或可继承上下文：'+obj
        # No arbitrary one-sentence limit. Explicit conflicting rooms need review.
        if obj in {'主卧','次卧','餐厅','客厅'} and not any(term in evidence for term in terms):
            others={'主卧','次卧','餐厅','客厅'}-{obj}
            if any(x in evidence for x in others):
                return 'rejected','当前直接证据指向其他房间，不能借前文套用：'+obj
        if re.search(r'尺度|面积',deepest):
            direct=[factual_scope(evidence[a:b],MARKETING) for a,b in clause_spans(evidence)]
            measured=[c for c in direct if DIMENSION.search(c)]
            if not measured:return 'rejected','没有直接尺寸与单位证据：'+obj
            # A comma-poor ASR clause may contain BOTH total area and a genuine
            # room measurement: "建面167㎡的下叠横向宽厅达到8.5米".
            # A total-area token must not erase the independently stated room size.
            room_measured=False
            for c in measured:
                for term in terms:
                    for match in re.finditer(re.escape(term),c):
                        tail=c[match.end():match.end()+30]
                        dimension=DIMENSION.search(tail)
                        if dimension and not re.search(r'建面|建筑面积|整套|总面积|户型面积',tail[:dimension.start()]):
                            room_measured=True
            if not room_measured and all(re.search(r'建面|建筑面积|整套|总面积|户型面积',c) for c in measured):
                return 'rejected','整套建筑面积不能当房间尺度'
            if not any(any(t in c for t in terms) and DIMENSION.search(c) for c in direct):
                return 'uncertain','尺寸与空间跨分句，需复核同对象指代，保留候选不武断删除'
    if re.search(r'起床|睡眠|起夜',deepest) and not re.search(r'智能|联动|模式|场景|自动控制',scoped):
        return 'rejected','睡眠影响不是智能模式'
    if tag.get('l4')=='中央空调' and re.search(r'预留|预埋|可选|未安装|没装',evidence):
        return 'uncertain','中央空调存在预留/未安装/选装表述，必须复核配置状态'
    return 'supported','未发现程序硬矛盾；必须结合独立模型定义审核'


def guard_for(unit):
    contexts={(a['tag_id'],a.get('evidence')):a.get('object_context','') for a in unit.get('labels',[])}
    return lambda evidence,tag:evidence_guard(evidence,tag,contexts.get((tag['tag_id'],evidence),''))


def assemble(doc,taxonomy,business,raw,metrics,payload,coverage_issues,review_ok):
    index=registry(taxonomy,doc['topic']);canonical,structure=canonicalize(raw,index)
    all_issues=list(dict.fromkeys(coverage_issues+structure))
    scoped=raw.get('coverage_scope')=='slice_local'
    local_semantic=set(str(x) for x in (raw.get('coverage') or {}).get('issues') or [])
    global_issues=[x for x in all_issues if not scoped or
        (x not in local_semantic and not x.startswith(('全文覆盖审核置信度不足','仍有证据/定义歧义标签：')))]
    # Add a validated dictionary-derived short alias, never a search-term alias.
    scoped_business=copy.deepcopy(business)
    for project in scoped_business['projects']:
        if project['id']=='P01' and any('臻澐' in a for a in project['aliases']):
            project['aliases']=list(dict.fromkeys(project['aliases']+['臻澐']))
    def review_factory(unit):
        issues=list(global_issues)
        accepted=unit.get('self_check') or {}
        checks=[]
        for a in unit.get('labels',[]):
            tag=index[a['choice_key']]
            state,reason=evidence_guard(a.get('evidence') or '',tag,a.get('object_context') or '')
            if state=='uncertain':issues.append('标签证据仍需复核：'+tag['tag_id']+' '+reason)
            checks.append({'tag_id':tag['tag_id'],'supported':state!='rejected',
                           'confidence':a.get('confidence'),'reason':a.get('why')})
        issues.extend(str(x) for x in accepted.get('issues') or [])
        scores=[accepted.get('confidence')] if scoped else [accepted.get('confidence'),(raw.get('coverage') or {}).get('confidence')]
        review_confidence=min(scores) if all(base.confidence(s) for s in scores) else None
        return {'pass':review_ok and not global_issues and accepted.get('pass') is True,
                'confidence':review_confidence,
                'issues':issues,'label_checks':checks,'验收方式':'独立全文全字典覆盖审核＋程序硬矛盾检查'}
    result=legacy.materialize_document(doc,taxonomy,scoped_business,canonical,metrics,payload,
                                       guard_factory=guard_for,review_factory=review_factory)
    result['coverage']=raw.get('coverage') if isinstance(raw,dict) else None
    result['coverage_issues']=all_issues
    # Semantic uncertainty routes to human review, not a processing failure.
    # Incomplete partition/schema/support consistency still blocks the smoke gate.
    partition_errors=[x for x in all_issues if any(t in x for t in [
        '不是对象','没有units','缺少全字典','格式错误','必须为字符串','歧义分区缺少',
        '重复或交叉','审核遗漏','非法编号','最终单元标签不一致','API失败'])]
    result['complete']=result['complete'] and review_ok and not partition_errors
    for trace in result['traces']:
        trace['标签回填方式']='固定字典选择编号；唯一字典名称兼容恢复；无模糊猜测'
        trace['全字典覆盖审核']=result['coverage'];trace['覆盖审核问题']=all_issues
    if not result['rows']:
        result['audit'].append({'原因':'独立全文全字典覆盖审核', '审核通过':review_ok and not all_issues,
                                '覆盖问题':all_issues,'coverage':result['coverage']})
    return result


def process_document(doc,taxonomy,business,runner):
    payload=legacy.request_payload(doc,taxonomy,business)
    payload['label_catalog']=catalogue(taxonomy,doc['topic'])
    draft,gm=runner.call(SYSTEM,payload,doc,'全文生成')
    if gm['status']!='success':
        result=legacy.materialize_document(doc,taxonomy,business,draft,gm,payload)
        result['coverage_issues']=['首轮API失败，未完成覆盖审核'];return result
    reviewed,rm=runner.call(REVIEW_SYSTEM,dict(payload,draft=draft,task='独立全文全字典覆盖审核，返回完整纠正结果'),doc,'全字典覆盖审核')
    ok=rm['status']=='success' and isinstance(reviewed,dict) and isinstance(reviewed.get('units'),list)
    if ok:
        index=registry(taxonomy,doc['topic'])
        coverage_issues=coverage_check(reviewed,index)+removal_check(draft,reviewed,index)
        result=assemble(doc,taxonomy,business,reviewed,rm,payload,coverage_issues,True)
    else:
        result=assemble(doc,taxonomy,business,draft,gm,payload,['独立覆盖审核API失败或结构错误，保留首轮待人工审核'],False)
    result['draft']=draft;result['reviewed']=reviewed;result['calls']=[gm,rm]
    result['label_changes']={'added_keys':sorted(selection_keys(reviewed,registry(taxonomy,doc['topic']))-selection_keys(draft,registry(taxonomy,doc['topic']))),
        'removed_keys':sorted(selection_keys(draft,registry(taxonomy,doc['topic']))-selection_keys(reviewed,registry(taxonomy,doc['topic']))),
        'removal_reasons':reviewed.get('removed_draft_labels') if isinstance(reviewed,dict) else None}
    for trace in result['traces']:trace['独立审核标签增删']=result['label_changes']
    return result


def load_baseline(path):
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    docs=[r['document'] for r in data['results']]
    if len({d['record_id'] for d in docs})!=len(docs):raise ValueError('Duplicate baseline source')
    return docs,data['sampling']


def smoke_anchor_errors(results):
    # Evidence-reviewed regression anchors are evaluation only, never model inputs.
    expected={
        'T2-75359':({'VOC-0165','VOC-0164','VOC-0416'},set()),
        'T2-8000912876517502735':({'VOC-0384','VOC-0380','VOC-0379'},set()),
        'T1-2651643050694719236':({'VOC-0203'},set()),
        'T2-C-7963753211120747179':(set(),{'VOC-0032','VOC-0019'}),
        'T2-C-7963753211120747182':(set(),{'VOC-0028','VOC-0029'}),
    }
    errors=[]
    by_source={r['document']['record_id']:r for r in results}
    for rid,(positive,negative) in expected.items():
        if rid not in by_source:
            errors.append('冒烟缺少已知问题来源：'+rid);continue
        calls=by_source[rid].get('calls') or []
        if calls and any(c.get('status')!='success' for c in calls):
            errors.append(rid+'：API阶段未成功，无法评估漏标/错标效果');continue
        selected={t['标签路径ID'] for row in by_source[rid]['rows'] for t in row['标签明细']}
        for tid in sorted(positive-selected):errors.append(rid+'：仍遗漏已知证据标签 '+tid)
        for tid in sorted(negative&selected):errors.append(rid+'：仍保留已知错误标签 '+tid)
    return errors


def expose_unknown_totals(data):
    """No zero-token/zero-cost claim when the gateway provided no usage."""
    calls=data.get('calls') or []
    summary=data['summary']
    if calls and not any(c.get('total_tokens') is not None for c in calls):
        summary['tokens']=None
    if calls and not any(c.get('estimated_yuan') is not None for c in calls):
        summary['estimated_yuan']=None
    for kind in ['文章','评论']:
        selected=[c for c in calls if c.get('source_type')==kind]
        if selected and not any(c.get('total_tokens') is not None for c in selected):
            summary[kind+'平均Token']=None
        if selected and not any(c.get('estimated_yuan') is not None for c in selected):
            summary[kind+'平均已知估算费用元']=None
    for row in data.get('tables',{}).get('Token费用',[]):
        selected=[c for c in calls if c.get('topic')==row['专题'] and c.get('source_type')==row['来源类型'] and c.get('phase')==row['阶段']]
        for column,field in [('输入Token','prompt_tokens'),('输出Token','completion_tokens'),('总Token','total_tokens'),('已知估算费用元','estimated_yuan')]:
            if selected and not any(c.get(field) is not None for c in selected):row[column]=None


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline',type=Path,default=Path(__file__).parent/'test_results_v51_20261009_api/delivery_results.json')
    p.add_argument('--taxonomy',type=Path,default=legacy.TAXONOMY)
    p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--concurrency',type=int,default=10)
    p.add_argument('--api-base-url',default='http://127.0.0.1:3000')
    p.add_argument('--model',default='qwen3.7-flash')
    p.add_argument('--prompt-key',action='store_true')
    p.add_argument('--smoke-only',action='store_true')
    p.add_argument('--prepare-only',action='store_true')
    args=p.parse_args()
    docs,sampling=load_baseline(args.baseline)
    taxonomy=base.load_taxonomy(args.taxonomy);business=base.load_business()
    args.output_dir.mkdir(parents=True,exist_ok=True)
    base.save_json(args.output_dir/'sample_manifest.json',sampling)
    base.save_json(args.output_dir/'selection_registry.json',{'taxonomy_signature':base.digest(taxonomy),
                   'catalogues':{topic:catalogue(taxonomy,topic) for topic in [base.T1,base.T2]}})
    print(base.dumps({'version':VERSION,'articles':sum(d['kind']=='文章' for d in docs),'comments':sum(d['kind']=='评论' for d in docs)}),flush=True)
    if args.prepare_only:return
    key=os.getenv('YS_LLM_API_KEY')
    if not key and args.prompt_key:key=getpass.getpass('API key (hidden, process only): ')
    base.VERSION=VERSION
    runner=base.ApiRunner(args.output_dir,args.concurrency,args.api_base_url,args.model,key=key);key=None
    signature=base.digest({'version':VERSION,'system':SYSTEM,'review':REVIEW_SYSTEM,'taxonomy':taxonomy,'business':business})
    def work(doc):
        checkpoint=args.output_dir/'documents'/(base.digest({'signature':signature,'document':doc})+'.json')
        if checkpoint.exists():
            old=json.loads(checkpoint.read_text(encoding='utf-8'))
            if old.get('complete'):return old
        try:result=process_document(doc,taxonomy,business,runner)
        except (ValueError,TypeError,KeyError,IndexError,AttributeError) as exc:
            result={'document':doc,'rows':[],'traces':[],'audit':[{'原因':'响应结构异常：'+str(exc),'原文':doc['text']}],
                    'complete':False,'calls':[c for c in runner.calls if c['record_id']==doc['record_id']]}
        base.save_json(checkpoint,result);return result
    # Real regression smoke before full same-source balanced rerun.
    ids=['T2-75359','T2-8000912876517502735','T1-2651643050694719236',
         'T2-C-7963753211120747179','T2-C-7963753211120747182']
    smoke=[next(d for d in docs if d['record_id']==rid) for rid in ids]
    comment_smoke=next(d for d in docs if d['kind']=='评论' and d['record_id'] not in ids)
    smoke.append(comment_smoke)
    with ThreadPoolExecutor(max_workers=min(args.concurrency,len(smoke))) as pool:
        results=list(pool.map(work,smoke))
    # Coverage completeness and structural success are a launch gate, not accuracy proof.
    anchor_errors=smoke_anchor_errors(results)
    base.save_json(args.output_dir/'smoke_anchor_checks.json',{'errors':anchor_errors,'checked_sources':ids})
    smoke_ok=all(r['complete'] for r in results) and not anchor_errors
    if smoke_ok and not args.smoke_only:
        done={d['record_id'] for d in smoke}
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futures={pool.submit(work,d):d for d in docs if d['record_id'] not in done}
            for future in as_completed(futures):
                results.append(future.result())
                if len(results)%10==0:print(base.dumps({'completed_sources':len(results),'planned_sources':len(docs)}),flush=True)
    order={d['record_id']:i for i,d in enumerate(docs)}
    results.sort(key=lambda r:order[r['document']['record_id']])
    legacy.reconcile_parent_relevance(results,business)
    data=base.export(args.output_dir,results,sampling,taxonomy,business,runner,'api',smoke_ok)
    data['summary'].update(version=VERSION,pipeline=globals().get('PIPELINE','全文＋固定编号全字典生成＋独立全字典覆盖审核'),
        verification_mode=globals().get('VERIFICATION_MODE','独立全文全字典审核＋程序硬矛盾检查'),
        mapping_contract='映射文章id=评论源表文章id；所属父文章ODS主键单独追溯',
        note='覆盖分区和模型置信度不是零漏标或实测准确率的证明；以逐项事实锚点和人工审核评估。',
        catalogue_counts={t:len(catalogue(taxonomy,t)) for t in [base.T1,base.T2]})
    data['summary']['smoke_anchor_errors']=anchor_errors
    expose_unknown_totals(data)
    data['taxonomy_source']=str(args.taxonomy)
    coverage_rows=[{'record_id':r['document']['record_id'],'来源类型':r['document']['kind'],
        '适用标签数':len(registry(taxonomy,r['document']['topic'])),
        '覆盖审核完整':not r.get('coverage_issues') and bool(r.get('coverage')),
        '覆盖问题':r.get('coverage_issues',[]),'审核分区':r.get('coverage')} for r in results]
    data['tables']['全字典覆盖审计']=coverage_rows
    data['schemas']['全字典覆盖审计']=list(coverage_rows[0]) if coverage_rows else []
    base.save_json(args.output_dir/'delivery_results.json',data)
    base.write_csv(args.output_dir/'全字典覆盖审计.csv',coverage_rows,data['schemas']['全字典覆盖审计'])
    print(base.dumps(data['summary']),flush=True)
    if not smoke_ok:raise SystemExit('Smoke incomplete; full batch not launched; checkpoints retained')
    if runner.fatal.is_set():raise SystemExit('Authentication failed; pending requests stopped')


if __name__=='__main__':main()
