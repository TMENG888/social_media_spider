"""Additive, dictionary-derived keyword fallback after semantic supplementation.

This stage never slices, rewrites, removes an old tag or borrows parent facts.
All topic-eligible directions are scanned. Only grounded, unambiguous supported
templates auto-append; other literal hits remain an explicit review queue.
No API is called by this deterministic stage.
"""
import argparse
import copy
import json
import re
import unicodedata
from collections import Counter
from functools import lru_cache
from pathlib import Path

import full_dictionary_supplement_v92 as core
from delivery_label_reference_v91 import display_emphases

VERSION = 'v94-keyword-fallback-after-single-unit-supplement'
RULE_VERSION = 'direction-core-words-v2'
NUM = r'[0-9零〇一二两三四五六七八九十百千万点壹贰叁肆伍陆柒捌玖拾佰仟,，.]+'
MEASURE = NUM + r'\s*(?:㎡|m²|m2|平方米|平米|平方呎|呎|米|cm|厘米|%)'
TRAD = str.maketrans('會泳廚衛臥陽臺層間數牆燈頂車庫門樓綠體積實寬風廳園觀別疊獨聯',
                     '会泳厨卫卧阳台层间数墙灯顶车库门楼绿体积实宽风厅园观别叠独联')
ALIASES = {
    '会所': ['会所'], '架空层': ['架空层'], '游泳池': ['游泳池', '泳池'],
    '瑜伽室': ['瑜伽室', '瑜伽房'], '棋牌室': ['棋牌室', '棋牌房'],
    '茶室': ['茶室'], '卫生间': ['卫生间', '卫浴间', '洗手间'],
    '阳台': ['阳台'], '厨房': ['厨房', '厨区'], '主卧': ['主卧'], '次卧': ['次卧'],
    '客厅': ['客厅', '起居室'], '餐厅': ['餐厅', '餐区', '饭厅'],
    '家政间': ['家政间', '家政房'], '衣帽间': ['衣帽间'], '玄关': ['玄关'],
    '景观': ['景观', '园林', '花园', '庭园'],
    '外立面': ['外立面', '立面', '外墙'],
    '电梯厅': ['电梯厅', '电梯', '轿厢'],
    '地下车库': ['地下车库', '地下停车库', '地下停车场', '车库'],
    '地下大堂': ['地下大堂', '地下门厅'], '大堂': ['大堂', '门厅'],
    '大门': ['社区大门', '小区大门', '大门', '府门'],
    '社区商业': ['社区商业', '社区底商', '小区底商'],
    '天花板': ['天花板', '吊顶', '顶面'], '墙体': ['墙体', '墙面'],
    '地板': ['地板', '地面'], '地面': ['地面', '地板'],
    '灯': ['灯具', '照明', '灯光'], '地漏': ['地漏'],
    '别墅': ['别墅', '叠墅', '叠拼', '联排别墅', '独栋别墅', '双拼别墅'],
    '大高': ['大高', '高层住宅'], '小高': ['小高', '小高层'],
    '超高': ['超高层住宅', '超高层', '超高住宅'],
    '整体风格': ['整体风格', '设计风格', '风格'],
    '面积': ['面积', '尺度'], '尺度': ['尺度', '面宽', '开间', '进深', '面积'],
    '数量': ['数量'], '建筑面积': ['建筑面积', '建面'],
    '健身房器械': ['健身房器械', '健身器械'],
    '材料': ['材料', '材质', '石灰岩', '铝板', '石材', '玻璃', '涂料', '金属', '真石漆'],
}
ROOMS = ['厨房', '主卧', '次卧', '客厅', '餐厅', '卫生间', '阳台', '衣帽间', '玄关', '家政间']
PUBLIC = ['会所', '架空层', '公园', '体育公园', '市政', '酒店', '学校', '健身馆', '社区商业',
          '地下车库', '地下大堂', '大堂', '景观', '外立面']
NUMERIC_FIELDS = {'数量', '面积', '尺度', '面宽', '进深', '建筑面积', '公摊面积', '赠送面积',
                  '得房率', '层高', '楼间距', '容积率', '楼栋数', '户数', '挑高', '容纳人数',
                  '总车位数量', '车位尺度', '车库出入口数量', '车位配比'}
GENERIC_FIELDS = {'其他', '整体', '资料', '类型', '格局', '通风', '风水', '墙', '门', '灯',
                  '人数', '年龄', '行业', '价格', '整体满意度', '生活服务', '空间尺度'}


@lru_cache(maxsize=8192)
def normalize(text):
    """Normalize for matching only; offsets always refer to untouched input."""
    output = []; offsets = []
    for pos, char in enumerate(text):
        value = unicodedata.normalize('NFKC', char).translate(TRAD).lower()
        for c in value:
            if not c.isspace(): output.append(c); offsets.append(pos)
    return ''.join(output), offsets


def variants(word):
    return list(dict.fromkeys(ALIASES.get(word, [word])))


def alternatives(word):
    return list(dict.fromkeys(v for part in re.split(r'[+/、]', word) if part for v in variants(part)))


def compile_rule(key, tag):
    """Derive object/attribute groups from real direction AND path, not tag IDs."""
    emphasis = tag['emphasis']; path = [tag.get('l'+str(i)) or '' for i in range(1, 6)]
    first, branch, space, attr, leaf = path
    groups = []; scope = None; mode = 'review'; numeric = False; count = False
    if first == '产品' and branch in {'户型', '精装', '公区'}:
        if branch == '户型':
            scope = space if space != '通用' else None
            feature = attr
            numeric = feature in NUMERIC_FIELDS
            count = feature == '数量'
            mode = 'numeric' if numeric else 'explicit'
            if feature in {'类型', '格局', '布局', '功能', '户型编号', '户型名称', '标准户型', '楼层', '风水'}:
                mode = 'review'
        elif branch == '精装':
            scope = space if space not in {'通用设备', '装修标准', '装修风格'} else None
            feature = attr
            mode = 'explicit' if space not in {'装修标准', '装修风格'} else 'review'
        else:
            scope = space
            feature = leaf or attr
            for prefix in [space+'功能', space+'规模', space+'运营', space]:
                if feature.startswith(prefix) and len(feature)>len(prefix): feature=feature[len(prefix):]
            numeric = feature in NUMERIC_FIELDS or any(w in feature for w in ['面积', '数量', '尺度', '人数'])
            mode = 'numeric' if numeric else 'explicit'
            if any(w in feature for w in ['风格', '运营', '等级', '收费', '时间', '系统', '管理', '智能', '性能']): mode='review'
        if scope: groups.append(variants(scope))
        if feature in {'外立面材料', '大门材质'}: feature='材料'
        if count:
            groups.append(['数量'])
        else:
            groups.append(alternatives(feature))
        if feature in GENERIC_FIELDS or (numeric and scope is None and attr not in {'建筑面积', '面宽', '进深', '得房率'}): mode='review'
    elif first == '产品' and branch == '物业形态':
        groups=[variants(space)]; mode='explicit'
    elif first == '产品' and branch == '总图规划':
        groups=[alternatives(emphasis.split('·')[-1])]
        numeric = space in NUMERIC_FIELDS
        mode='numeric' if numeric else 'review'
    else:
        groups=[alternatives(part) for part in emphasis.split('·') if part]
        # Outside product configuration, mere words often miss the actor,
        # time, service phase, personal identity, or numerical basis.
        mode='review'
    groups=[g for g in groups if g]
    from gym_policy_v96 import enabled
    gym_policy = enabled(tag)
    if gym_policy: groups=[variants('会所'),['健身房','健身器械','健身房器械']]
    return {'key':key, 'tag_id':tag['tag_id'], 'emphasis':emphasis, 'path':path, 'gym_policy_v96':gym_policy,
            'groups':groups, 'scope':scope, 'mode':mode, 'numeric':numeric,
            'count':count, 'rule_version':RULE_VERSION}


def occurrences(text, words):
    norm, offsets=normalize(text); found=[]
    for word in words:
        needle=normalize(word)[0]
        if not needle: continue
        for match in re.finditer(re.escape(needle), norm):
            start=offsets[match.start()]; end=offsets[match.end()-1]+1
            found.append({'term':word, 'start':start, 'end':end, 'quote':text[start:end]})
    return sorted(found, key=lambda x:(x['start'], -len(x['quote'])))


def sentence_ranges(text):
    """Do not match across sentence endings or comment-speaker boundaries."""
    cursor=0
    pattern=r'[。！？!?；;\n]|【(?:父评论|子评论[^｜】]*)(?:｜[^】]*)?】'
    for match in re.finditer(pattern, text):
        if text[cursor:match.start()].strip(): yield cursor,match.start()
        cursor=match.end()
    if text[cursor:].strip(): yield cursor,len(text)


def count_matches(text, scope):
    hits=[]
    for word in variants(scope):
        escaped=re.escape(word)
        patterns=[NUM+r'\s*(?:个|间|套)\s*(?:独立|专用|单独)?'+escaped+r'(?!门|窗|设备|电器|灶|台)',
                  escaped+r'(?:数量)?\s*(?:为|有|共|:|：)\s*'+NUM+r'\s*(?:个|间|套)',
                  r'(?:双|两间|两套|单)'+escaped]
        for pattern in patterns:
            for m in re.finditer(pattern,text): hits.append({'term':'明确计数', 'start':m.start(),'end':m.end(),'quote':m.group()})
    return hits


def find_hits(unit, rule):
    hits=[]
    for start,end in sentence_ranges(unit['text']):
        text=unit['text'][start:end]
        buckets=[occurrences(text,g) for g in rule['groups']]
        if rule['count'] and rule['scope']:
            buckets[-1] += count_matches(text.translate(TRAD),rule['scope'])
            # Count offsets stay valid because character translation is 1:1.
            for h in buckets[-1]: h['quote']=text[h['start']:h['end']]
        if not buckets or not all(buckets): continue
        # Pick the closest literal combination, not whole-slice co-occurrence.
        for anchor in buckets[-1]:
            selected=[min(b, key=lambda m:abs(m['start']-anchor['start'])) for b in buckets[:-1]]+[anchor]
            lo=min(m['start'] for m in selected); hi=max(m['end'] for m in selected)
            if hi-lo>140: continue
            if hits and any(h['sentence_start']==start and h['window_start']==lo and h['window_end']==hi for h in hits): continue
            hits.append({'sentence_start':start, 'sentence_end':end, 'window_start':lo,'window_end':hi,
                         'quote':text, 'matches':[{**m,'start':start+m['start'],'end':start+m['end']} for m in selected]})
    return hits


def hit_issues(hit, rule, unit, result):
    text=hit['quote']; norm=normalize(text)[0]; issues=[]
    if re.search(r'没有|没设|未设|并非|不是|不设|不含|不包括|无(?:会所|泳池|游泳池|厨房|阳台)|取消|不存在',norm):
        issues.append('存在否定或对比，关键词不能证明配置归属')
    if re.search(r'是否|有没有|\?|？|吗|如果|假如|希望|想要|建议|应该|最好|可能|据说|传闻',text):
        issues.append('提问、条件、意愿或不确定说法，不能直接当已确认配置')
    if re.search(r'#{1}|标签词|标签体系|举例|例如|关键词',text): issues.append('可能是话题词、举例或标签目录，不直接当项目事实')
    if rule['mode']=='review': issues.append('该定义需要主体、属性口径或语义判断，核心字眼只形成待核候选')
    if rule['numeric']:
        count_ok=rule['count'] and count_matches(text.translate(TRAD),rule['scope'])
        if not count_ok and not re.search(MEASURE, text, re.I):
            issues.append('未取得该对象的明确数值与单位，不能由出现对象推算数量/尺度')
        if rule['count'] and not count_ok: issues.append('缺少与该空间直接绑定的明确计数')
    # Nearest competing room/space before the attribute prevents distant words
    # in a list from supplying ownership to an unrelated attribute.
    attr=hit['matches'][-1]; scope=rule['scope']
    if scope:
        competing=ROOMS if scope in ROOMS else PUBLIC
        own=hit['matches'][0]; others=[]
        count_contains_object=rule['count'] and attr['start']<=own['start'] and own['end']<=attr['end']
        if own['start']>attr['start'] and not count_contains_object:
            issues.append('对象出现在属性之后，须核对是否属于同一对象，不能仅靠反向共现补标')
        bridge=unit['text'][own['end']:attr['start']].strip()
        shared_material=rule['path'][2]=='外立面' and rule['path'][3]=='外立面材料' and re.search(r'采用|使用|选用',bridge)
        if re.match(r'^(?:和|与|及|、)',bridge) and not shared_material:
            issues.append('对象与设施并列列举，不能把独立设施自动当成对象内部配置')
        if re.search(r'另一个项目|另一项目|另一个楼盘|其他楼盘|隔壁楼盘|对面楼盘',bridge):
            issues.append('核心字眼之间发生项目切换，不直接继承前一个空间对象')
        for name in competing:
            for found in occurrences(text,variants(name)):
                absolute=hit['sentence_start']+found['start']
                if absolute<=attr['start'] and absolute>=own['start']:
                    others.append((absolute,name))
        if others:
            nearest=max(others,key=lambda x:x[0])[1]
            if nearest!=scope:
                # The word "公园" inside "体育公园" has the same effect.
                issues.append('属性附近出现其他空间：'+nearest+'，不能仅靠同片共现借给'+scope)
        if scope in {'会所','架空层'} and re.search(r'附近|周边|隔壁|旁边|邻近|毗邻|邻近|外面',text):
            issues.append('出现周边/相邻关系，须确认是本项目内部配置而不是外部设施')
    elif rule['path'][1]=='户型':
        # Whole-home dimensions cannot be borrowed from a named individual room.
        before=text[:attr['start']-hit['sentence_start']]
        if any(occurrences(before,variants(space)) for space in ROOMS):
            issues.append('整户指标附近存在具体房间对象，须核对数值测量对象')
        if rule['numeric']:
            local_start=attr['start']-hit['sentence_start'];local_end=attr['end']-hit['sentence_start']
            local=text[max(0,local_start-35):min(len(text),local_end+55)]
            if re.search(r'阳台|主卧|次卧|客厅|餐厅|厨房|会所',text[local_end:local_end+25]):
                issues.append('尺寸后紧接具体空间，不能把空间尺寸当整户指标')
            if rule['path'][3]=='建筑面积':
                home=r'户型|洋房|上叠|中叠|下叠|平层|住宅单元|房源|大宅|\d+居|\d+房'
                prefix=text[max(0,local_start-30):local_start]
                postfix=text[local_end:local_end+55]
                if re.search(r'总建筑|地上建筑|规划建筑|计容建|宗地|小区概况',text[max(0,local_start-30):local_end]):
                    issues.append('数值为总量、地块或计容建筑面积，不直接补户型建筑面积')
                elif not re.search(home,prefix+postfix):
                    issues.append('建筑面积尚未明确属于整户房源，不能用项目总量补户型面积')
    if scope=='景观' and rule['numeric']:
        object_word=r'(?:景观|园林|花园|庭园|绿地)'
        amount=NUM+r'\s*(?:㎡|m²|m2|平方米|平米|万方|方)'
        attached=re.search(object_word+r'(?:占地)?(?:面积)?[^，。；;!?！？]{0,10}'+amount,text,re.I)
        reversed_attached=re.search(amount+r'[^，。；;!?！？]{0,10}'+object_word,text,re.I)
        if not (attached or reversed_attached):issues.append('未取得与景观直接绑定的面积数值，不能借住宅/会所面积')
        if re.search(r'户型|建筑面积|建面|主卧|客厅',text):issues.append('同句存在房源面积，景观面积须另行语义核对')
    if rule['path'][1]=='物业形态' and re.search(r'可(?:以)?批量|可(?:以)?不断|其他项目|别的项目|相比|对比|不如|只是|并非|堪比|媲美|远超|胜过|超过',text):
        issues.append('业态用于一般比较，未确认本项目实际类型')
    if rule['path'][1]=='物业形态' and re.search(r'追求|想住|想买|寻求|寻找|考虑买|考虑购买',text):
        issues.append('业态用于意愿或目标客群描述，不能仅凭字眼确认项目实际类型')
    if not scope and rule['mode']=='explicit' and len(normalize(text)[0])<len(normalize(rule['emphasis'])[0])+2:
        issues.append('仅孤立名称或标题，未取得实际配置描述')
    history=core.historic_rejections(result,unit['unit_id'],rule['key'])
    if rule.get('gym_policy_v96'):
        from gym_policy_v96 import relation_issue,obsolete_refusal
        issue=relation_issue(unit['text'],hit['matches'][0]['end'],hit['matches'][-1]['start'])
        if issue: issues.append(issue)
        history=[reason for reason in history if not obsolete_refusal(reason)]
    if history: issues.append('已有对象/定义否决或争议，不能用关键词无理由覆盖：'+'；'.join(history))
    from final_definition_guard_v92 import final_scope_risks
    tag={**{'l'+str(n):value for n,value in enumerate(rule['path'],1)},'emphasis':rule['emphasis']}
    issues+=final_scope_risks({'key':rule['key'],'quotes':[text],'context_quotes':[]},{rule['key']:tag},result.get('document'))
    return list(dict.fromkeys(issues))


def grounded_event(hit,rule,unit,result,issues):
    start=unit['start']+hit['sentence_start']; end=unit['start']+hit['sentence_end']
    quote=result['document']['text'][start:end]
    assert quote==hit['quote']
    return {'unit_id':unit['unit_id'], 'key':rule['key'], 'object':rule['scope'] or rule['emphasis'],
            'quotes':[quote], 'context_quotes':[],
            'attribute_spans':[{'start':start,'end':end,'quote':quote}], 'object_spans':[],
            'keyword_matches':[{**m,'start':unit['start']+m['start'],'end':unit['start']+m['end']} for m in hit['matches']],
            'rule_version':RULE_VERSION, 'decision_method':'字典强调方向核心字眼及对象属性规则',
            'confidence':None, 'program_issues':issues, 'reason':('；'.join(issues) if issues else
                '原文同时命中“'+('、'.join(m['quote'] for m in hit['matches']))+'”，对象、属性位于同一原句，规则必要条件已满足；保留原文限定。'),
            '处理':'关键词补标待核' if issues else '关键词规则直接补标',
            '原因':'；'.join(issues) if issues else '同对象核心字眼有逐字证据，按真实字典追加，不修改原摘要或情绪'}


def process(result,taxonomy):
    """Idempotent additive final stage: current delivered units only."""
    result=copy.deepcopy(result); index=core.index_for(taxonomy,result['document']['topic'])
    rules=[compile_rule(k,t) for k,t in index.items()]
    units={u['unit_id']:u for u in core.audit_units(result)}; traces={t['unit_id']:t for t in result['traces']}
    events=[]; new=0; existing_hits=0; hits_count=0
    for row in result['rows']:
        uid=row['unit_id']; unit=units[uid]; present={'D'+t['标签路径ID'][4:] for t in row['标签明细']}
        for rule in rules:
            hits=find_hits(unit,rule)
            if not hits: continue
            hits_count+=1
            if rule['key'] in present:
                existing_hits+=1
                events.append({'unit_id':uid,'key':rule['key'],'处理':'关键词命中已有标签，不重复添加','原因':'片内相同标签路径ID已存在',
                               'quotes':[hits[0]['quote']], 'context_quotes':[], 'rule_version':RULE_VERSION})
                continue
            choices=[(hit,hit_issues(hit,rule,unit,result)) for hit in hits]
            hit,issues=min(choices,key=lambda x:len(x[1]))
            event=grounded_event(hit,rule,unit,result,issues);events.append(event)
            if issues: continue
            added=core.append_confirmed(row,traces[uid],event,index,result['document'],unit)
            assert added
            traces[uid].setdefault('关键词补标证据',[]).append(copy.deepcopy(event))
            row['备注']=(row.get('备注') or '')+'；关键词兜底补标'+rule['tag_id']+'（保留原文限定，需人工验收）'
            present.add(rule['key']);new+=1
        row['标签强调方向']=display_emphases(row['标签明细'])
    previous=result.get('keyword_supplement_events',[])
    # Keep historical additions when resumed, but do not multiply audit events.
    merged={(e['unit_id'],e['key'],e['处理']):e for e in previous}
    for e in events:
        if e['处理']=='关键词命中已有标签，不重复添加' and any(x['unit_id']==e['unit_id'] and x['key']==e['key'] and x['处理']=='关键词规则直接补标' for x in previous): continue
        merged[(e['unit_id'],e['key'],e['处理'])]=e
    result['keyword_supplement_events']=list(merged.values())
    result['keyword_supplement_deferred']=[e for e in merged.values() if e['处理']=='关键词补标待核']
    # Existing audit sheet remains the single place for supplements and review.
    old_events={(e['unit_id'],e.get('key'),e['处理']):e for e in result.get('label_supplement_events',[])}
    for e in merged.values(): old_events[(e['unit_id'],e['key'],e['处理'])]=e
    result['label_supplement_events']=list(old_events.values())
    deferred=core.unique_deferred(result.get('label_supplement_deferred',[])+result['keyword_supplement_deferred'])
    result['label_supplement_deferred']=deferred
    coverage=result['label_supplement_coverage']
    coverage['deferred_candidate_count']=len(deferred)
    if result['keyword_supplement_deferred']: coverage['all_candidates_adjudicated']=False; result['complete']=False
    result['keyword_supplement_coverage']={'version':VERSION,'rule_version':RULE_VERSION,'eligible_labels':len(index),
        'target_units':len(result['rows']),'checked_unit_label_pairs':len(result['rows'])*len(index),
        'literal_hit_pairs':hits_count,'existing_hit_pairs':existing_hits,
        'direct_added_pairs':sum(e['处理']=='关键词规则直接补标' for e in merged.values()),
        'new_this_invocation':new,'review_pairs':len(result['keyword_supplement_deferred']),
        'api_calls':0,'input_tokens':0,'output_tokens':0,'estimated_yuan':0,
        'scope':'只扫描当前交付单元；属性不借父文章/其他切片；不改变切片、项目、摘要、情绪、已有标签'}
    result['version']=VERSION
    return result


def validate(prior,current,taxonomy):
    core.validate_contract(prior,current['results'],taxonomy)
    before={r['document']['record_id']:r for r in prior['results']}
    total=Counter()
    for r in current['results']:
        old=before[r['document']['record_id']]
        assert r['document']==old['document']
        assert [u['unit_id'] for u in r['rows']]==[u['unit_id'] for u in old['rows']], 'Fallback cannot add/remove units'
        for row,previous in zip(r['rows'],old['rows']):
            old_tags={t['标签路径ID'] for t in previous['标签明细']};new_tags={t['标签路径ID'] for t in row['标签明细']}
            assert old_tags<=new_tags
            for k,v in previous.items():
                if k not in {'标签明细','标签强调方向','打标说明','备注','验收状态'}: assert row[k]==v,(row['unit_id'],k)
            assert row['打标说明'].startswith(previous['打标说明'])
            total['new_tags']+=len(new_tags-old_tags)
    return {'passed':True,'sources':len(current['results']),**total,
            'checks':['旧标签完整保留','原切片及评论完整','摘要身份指数不变','真实字典回填','关键词命中逐字定位','片内同ID去重']}


def apply_file(input_path,output_dir,taxonomy_path,prior_path=None):
    data=json.loads(input_path.read_text(encoding='utf-8'));prior=json.loads((prior_path or input_path).read_text(encoding='utf-8'))
    baseline=copy.deepcopy(data); taxonomy=core.base.load_taxonomy(taxonomy_path)
    data['results']=[process(r,taxonomy) for r in data['results']]
    contract=validate(baseline,data,taxonomy)
    old={r['document']['record_id']:r for r in prior['results']}
    for r in data['results']:
        before={(u['unit_id'],'D'+t['标签路径ID'][4:]) for u in old[r['document']['record_id']]['rows'] for t in u['标签明细']}
        after={(u['unit_id'],'D'+t['标签路径ID'][4:]) for u in r['rows'] for t in u['标签明细']}
        c=r['label_supplement_coverage'];c['new_confirmed_tags']=len(after-before);c['withdrawn_wrong_tags']=len(before-after)
        c['restored_units']=len({u['unit_id'] for u in r['rows']}-{u['unit_id'] for u in old[r['document']['record_id']]['rows']})
    data['summary'].update(version=VERSION,keyword_fallback_enabled=True,keyword_rule_version=RULE_VERSION)
    data['keyword_supplement_status']={'version':VERSION,'sources':len(data['results']),
        'scanned_units':sum(len(r['rows']) for r in data['results']),
        'scanned_unit_label_pairs':sum(r['keyword_supplement_coverage']['checked_unit_label_pairs'] for r in data['results']),
        'direct_added_pairs':sum(r['keyword_supplement_coverage']['direct_added_pairs'] for r in data['results']),
        'new_this_invocation':contract.get('new_tags',0),
        'review_pairs':sum(r['keyword_supplement_coverage']['review_pairs'] for r in data['results']),
        'api_calls':0,'input_tokens':0,'output_tokens':0,'estimated_yuan':0,'zero_miss_guarantee':False}
    for status,counter in [('new_tags','new_confirmed_tags'),('withdrawn_wrong_tags','withdrawn_wrong_tags'),('restored_units','restored_units')]:
        data['supplement_status'][status]=sum(r['label_supplement_coverage'][counter] for r in data['results'])
    data['supplement_status']['deferred_candidates']=sum(len(r['label_supplement_deferred']) for r in data['results'])
    data['supplement_status']['sources_with_deferred_candidates']=sum(bool(r['label_supplement_deferred']) for r in data['results'])
    for topic,kind in [(core.base.T1,'产品信息单元'),(core.base.T2,'观点信息单元')]:
        data['tables'][kind]=[u for r in data['results'] if r['document']['topic']==topic for u in r['rows']]
    # Distinguish reused baseline usage from zero-cost deterministic additions.
    if not (output_dir/'calls').exists():
        data['baseline_token_cost']=copy.deepcopy(data.get('current_run_token_cost'))
        data.pop('current_run_token_cost',None);data['supplement_call_costs']={}
    output_dir.mkdir(parents=True,exist_ok=True)
    core.save_json(output_dir/'delivery_results.json',data)
    core.save_json(output_dir/'keyword_supplement_verification.json',contract)
    core.save_json(output_dir/'keyword_supplement_summary.json',data['keyword_supplement_status'])
    core.save_json(output_dir/'keyword_rules.json',{topic:[compile_rule(k,t) for k,t in core.index_for(taxonomy,topic).items()] for topic in [core.base.T1,core.base.T2]})
    return data['keyword_supplement_status']


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--input',type=Path,required=True);ap.add_argument('--output-dir',type=Path,required=True)
    ap.add_argument('--taxonomy',type=Path,default=core.DEFAULT_TAXONOMY);ap.add_argument('--prior',type=Path)
    args=ap.parse_args();print(json.dumps(apply_file(args.input,args.output_dir,args.taxonomy,args.prior),ensure_ascii=False))
