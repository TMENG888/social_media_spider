"""Frozen slice + existing dictionary labels, with original evidence safeguards.

Label words expand candidates, not facts. Attributes/numbers must occur in the
target slice. An inherited object must have a grounded prior-label proof, and
no speaker, space, project or numerical-basis switch may intervene. No API.
"""
import argparse
import copy
import json
import re
from collections import Counter
from pathlib import Path

import keyword_supplement_v94 as k

core = k.core
VERSION = 'v95-joint-slice-frozen-label-keyword-supplement'
RULE_VERSION = 'joint-direction-core-words-v1'
LABEL_FIELDS = ['一级标签','二级标签','三级标签','四级标签','五级标签','标签强调方向']


def label_text(tag):
    # Deliberately exclude tag IDs, row numbers and label ordinals: they are
    # not property amounts. Never concatenate JSON keys into factual evidence.
    return ' '.join(str(tag.get(field) or '') for field in LABEL_FIELDS)


def snapshot_labels(row, trace, index):
    if '联合补标初始标签快照' not in trace:
        trace['联合补标初始标签快照'] = copy.deepcopy(row['标签明细'])
    frozen = trace['联合补标初始标签快照']
    for tag in frozen:
        key = 'D'+tag['标签路径ID'][4:]
        if key not in index or tag != core.label_json(index[key]):
            raise ValueError('Frozen source label does not exactly match topic dictionary')
    return frozen


def union_matches(unit, rule, frozen):
    """Full eligible dictionary; match every group in raw+label union once."""
    buckets=[]
    for group_no, words in enumerate(rule['groups']):
        matches=[dict(m, source='切片原文', group=group_no) for m in k.occurrences(unit['text'], words)]
        if rule['count'] and group_no==len(rule['groups'])-1 and rule['scope']:
            matches += [dict(m, source='切片原文', group=group_no) for m in k.count_matches(unit['text'].translate(k.TRAD),rule['scope'])]
        for tag in frozen:
            matches += [dict(m, source='已有标签明细', source_tag_id=tag['标签路径ID'], group=group_no,
                            field_text=label_text(tag)) for m in k.occurrences(label_text(tag), words)]
        if not matches:return []
        buckets.append(matches)
    return buckets


def source_object_anchors(unit, rule, frozen, trace, index, result):
    """Ground a frozen label's space hint in that label's original evidence."""
    if not rule['scope']:return []
    anchors=[];seen=set()
    proofs=trace.get('标签证据与归属',[])+trace.get('全字典补选证据',[])
    for tag in frozen:
        key='D'+tag['标签路径ID'][4:]
        source_rule=k.compile_rule(key,index[key])
        if source_rule['scope']!=rule['scope']:continue
        if core.historic_rejections(result,unit['unit_id'],key):continue
        for proof in proofs:
            if proof.get('key',proof.get('choice_key'))!=key:continue
            if proof.get('program_issues') or proof.get('_evidence_issues'):continue
            if proof.get('verdict') in {'unsupported','uncertain'}:continue
            spans=proof.get('attribute_spans',[])+proof.get('object_spans',[])
            for span in spans:
                a,b=span.get('start'),span.get('end');quote=span.get('quote')
                if not isinstance(a,int) or not isinstance(b,int):continue
                if not unit['start']<=a<b<=unit['end']:continue
                if result['document']['text'][a:b]!=quote:continue
                objects=k.occurrences(quote,k.variants(rule['scope']))
                # A literal universal bedroom statement also covers a main /
                # secondary bedroom already identified by a grounded label.
                # This is not an alias: mark the inclusion inference explicitly.
                if rule['scope'] in {'主卧','次卧'} and proof.get('confidence',0) is not None and proof.get('confidence',0)>=.9:
                    for match in re.finditer(r'(?:每(?:一)?(?:间|个)|所有|全部)(?:的)?卧室',quote):
                        objects.append({'term':'全称卧室范围','start':match.start(),'end':match.end(),'quote':match.group(),
                                        'universal_scope':True})
                for obj in objects:
                    start=a-unit['start']+obj['start'];end=a-unit['start']+obj['end']
                    signature=(tag['标签路径ID'],start,end)
                    if signature in seen:continue
                    seen.add(signature)
                    anchors.append(dict(obj,start=start,end=end,source_tag_id=tag['标签路径ID'],
                                        source_label_text=label_text(tag),source_proof_span=copy.deepcopy(span)))
    return anchors


def inherited_hits(unit,rule,frozen,trace,index,result):
    if not rule['scope'] or len(rule['groups'])!=2:return []
    anchors=source_object_anchors(unit,rule,frozen,trace,index,result)
    sentences=list(k.sentence_ranges(unit['text']));hits=[]
    for a,b in sentences:
        attributes=k.occurrences(unit['text'][a:b],rule['groups'][-1])
        if rule['count']:
            attributes+=k.count_matches(unit['text'][a:b].translate(k.TRAD),rule['scope'])
        for attr in attributes:
            attr=dict(attr,start=a+attr['start'],end=a+attr['end'])
            for own in anchors:
                if not own['end']<=attr['start'] or attr['end']-own['start']>140:continue
                # Same-sentence matching is already handled in v94; this branch
                # adds only a proved continuing object across sentence endings.
                prior=next(((x,y) for x,y in sentences if x<=own['start']<y),None)
                if not prior:continue
                if prior[0]==a and not own.get('universal_scope'):continue
                if sum(x>=prior[0] and x<a for x,y in sentences)>1:continue
                start=prior[0];end=b
                hits.append({'sentence_start':start,'sentence_end':end,'window_start':own['start'],
                    'window_end':attr['end'],'quote':unit['text'][start:end],
                    'matches':[dict(own),dict(attr)],'inherited_object':dict(own),
                    'attribute_sentence':unit['text'][a:b],'attribute_sentence_start':a,'attribute_sentence_end':b})
    return hits


def inherited_issues(hit,rule,unit,result):
    issues=k.hit_issues(hit,rule,unit,result)
    bridge=unit['text'][hit['matches'][0]['end']:hit['matches'][-1]['start']]
    if re.search(r'【|】|\n\s*\n|另(?:一|个)|其他|对面|隔壁|相比|对比|转而|但是|而(?:在|另)|至于',bridge):
        issues.append('对象证据与属性之间有发言者、段落或对象切换，不继承已有标签对象')
    # Numeric facts require direct binding, not an area anywhere in the combined
    # context. Conservatively send these inherited candidates for adjudication.
    if rule['numeric']:issues.append('跨句数值需核对测量对象及口径，联合字眼不直接确认')
    if rule['scope'] in k.ROOMS:
        for space in k.PUBLIC:
            if k.occurrences(bridge,k.variants(space)):
                issues.append('延续范围内出现公区对象，不从房间标签借归属');break
    if rule['scope'] in k.PUBLIC:
        for space in k.ROOMS:
            if k.occurrences(bridge,k.variants(space)):
                issues.append('延续范围内出现套内房间，不从公区标签借归属');break
    if re.search(r'户型|\d+\s*(?:㎡|平米|平方米).*?(?:户|房)|(?:另一|另一个)项目',bridge):
        issues.append('延续范围内可能切换户型或项目，不能跨对象补标')
    return list(dict.fromkeys(issues))


def joint_event(unit,rule,buckets,hit,result,issues):
    label_only=bool(issues and issues[0].startswith('具体属性只在已有标签'))
    event={'unit_id':unit['unit_id'],'key':rule['key'],'object':rule['scope'] or rule['emphasis'],
        'rule_version':RULE_VERSION,'decision_method':'切片原文与冻结已有标签联合检查',
        'confidence':None,'program_issues':issues,'联合核心字眼':buckets,
        '处理':'联合关键词不补标（仅标签有属性）' if label_only else '联合关键词补标待核' if issues else '联合关键词规则直接补标',
        '原因':'；'.join(issues) if issues else '已有标签的对象证据与原文属性连续且未切换对象，按真实字典追加'}
    if not hit:
        event.update(quotes=[],context_quotes=[],attribute_spans=[],object_spans=[],keyword_matches=[],
                     reason='；'.join(issues))
        return event
    start=unit['start']+hit['attribute_sentence_start'];end=unit['start']+hit['attribute_sentence_end']
    own=hit['inherited_object'];obj_start=unit['start']+own['start'];obj_end=unit['start']+own['end']
    attr_quote=result['document']['text'][start:end];object_quote=result['document']['text'][obj_start:obj_end]
    event.update(quotes=[attr_quote],context_quotes=[object_quote],
        attribute_spans=[{'start':start,'end':end,'quote':attr_quote}],
        object_spans=[{'start':obj_start,'end':obj_end,'quote':object_quote}],
        keyword_matches=[dict(m,start=unit['start']+m['start'],end=unit['start']+m['end'],source='切片原文') for m in hit['matches']],
        source_label_id=own['source_tag_id'],source_label_text=own['source_label_text'],
        source_label_proof=own['source_proof_span'],
        object_binding_method='原文全称卧室范围覆盖已有卧室对象' if own.get('universal_scope') else '连续原文对象继承',
        reason='；'.join(issues) if issues else '已有标签'+own['source_tag_id']+'提示对象“'+rule['scope']+'”，原文对象证据“'+object_quote+
               '”后连续说明“'+attr_quote+'”；对象和属性均可定位且未切换，新增事实不从标签文字推断。')
    return event


def process(result,taxonomy):
    result=copy.deepcopy(result);index=core.index_for(taxonomy,result['document']['topic'])
    traces={t['unit_id']:t for t in result['traces']}
    frozen={r['unit_id']:snapshot_labels(r,traces[r['unit_id']],index) for r in result['rows']}
    # Keep the original raw-text fallback, but never feed its new labels back
    # into this invocation's object sources (fixed input snapshot above).
    result=k.process(result,taxonomy)
    units={u['unit_id']:u for u in core.audit_units(result)};traces={t['unit_id']:t for t in result['traces']}
    prior_events=result.get('joint_keyword_supplement_events',[])
    events={(e['unit_id'],e['key']):e for e in prior_events}
    count=Counter()
    for row in result['rows']:
        uid=row['unit_id'];unit=units[uid];present={'D'+t['标签路径ID'][4:] for t in row['标签明细']}
        for key,tag in index.items():
            rule=k.compile_rule(key,tag);buckets=union_matches(unit,rule,frozen[uid])
            if not buckets:continue
            count['union_hit_pairs']+=1
            if key in present:
                count['existing_union_hit_pairs']+=1;continue
            # Literal candidates already checked by the existing fallback are
            # not duplicated in the joint-only audit queue.
            if k.find_hits(unit,rule):continue
            count['joint_only_candidate_pairs']+=1
            attrs=k.occurrences(unit['text'],rule['groups'][-1])
            hits=inherited_hits(unit,rule,frozen[uid],traces[uid],index,result)
            if hits:
                choices=[(h,inherited_issues(h,rule,unit,result)) for h in hits]
                hit,issues=min(choices,key=lambda c:len(c[1]))
            else:
                hit=None
                issues=['具体属性只在已有标签中出现，原文没有对应事实，不允许标签推导标签'] if not attrs else [
                    '联合核心字眼命中，但未取得已有标签的连续同对象原文证据，不能仅靠共现补标']
            event=joint_event(unit,rule,buckets,hit,result,issues);events[(uid,key)]=event
            if issues:continue
            assert core.append_confirmed(row,traces[uid],event,index,result['document'],unit)
            traces[uid].setdefault('联合关键词补标证据',[]).append(copy.deepcopy(event))
            row['备注']=(row.get('备注') or '')+'；联合关键词补标'+tag['tag_id']+'（原文事实有据，需人工验收）'
            present.add(key);count['new_this_invocation']+=1
        row['标签强调方向']=k.display_emphases(row['标签明细'])
    result['joint_keyword_supplement_events']=list(events.values())
    result['joint_keyword_supplement_deferred']=[e for e in events.values() if e['处理']=='联合关键词补标待核']
    all_events={(e['unit_id'],e.get('key'),e['处理']):e for e in result.get('label_supplement_events',[])}
    for e in events.values():all_events[(e['unit_id'],e['key'],e['处理'])]=e
    result['label_supplement_events']=list(all_events.values())
    result['label_supplement_deferred']=core.unique_deferred(result.get('label_supplement_deferred',[])+result['joint_keyword_supplement_deferred'])
    coverage=result['label_supplement_coverage'];coverage['deferred_candidate_count']=len(result['label_supplement_deferred'])
    if result['joint_keyword_supplement_deferred']:coverage['all_candidates_adjudicated']=False;result['complete']=False
    result['joint_keyword_supplement_coverage']={'version':VERSION,'rule_version':RULE_VERSION,'eligible_labels':len(index),
        'target_units':len(result['rows']),'checked_unit_label_pairs':len(result['rows'])*len(index),**count,
        'direct_added_pairs':sum(e['处理']=='联合关键词规则直接补标' for e in events.values()),
        'label_only_not_added_pairs':sum(e['处理']=='联合关键词不补标（仅标签有属性）' for e in events.values()),
        'review_pairs':len(result['joint_keyword_supplement_deferred']),
        'api_calls':0,'input_tokens':0,'output_tokens':0,'estimated_yuan':0,
        'frozen_labels':True,'attributes_from_original_only':True}
    result['version']=VERSION
    return result


def apply_file(input_path,output_dir,taxonomy_path,prior_path=None):
    data=json.loads(input_path.read_text(encoding='utf-8'));baseline=copy.deepcopy(data)
    prior=json.loads((prior_path or input_path).read_text(encoding='utf-8'));taxonomy=core.base.load_taxonomy(taxonomy_path)
    data['results']=[process(r,taxonomy) for r in data['results']]
    contract=k.validate(baseline,data,taxonomy);before={r['document']['record_id']:r for r in prior['results']}
    for result in data['results']:
        old=before[result['document']['record_id']]
        prior_pairs={(r['unit_id'],t['标签路径ID']) for r in old['rows'] for t in r['标签明细']}
        after={(r['unit_id'],t['标签路径ID']) for r in result['rows'] for t in r['标签明细']}
        result['label_supplement_coverage'].update(new_confirmed_tags=len(after-prior_pairs),withdrawn_wrong_tags=len(prior_pairs-after),restored_units=0)
    data['summary'].update(version=VERSION,keyword_fallback_enabled=True,joint_keyword_fallback_enabled=True,keyword_rule_version=RULE_VERSION)
    data['joint_keyword_supplement_status']={'version':VERSION,'sources':len(data['results']),
        'scanned_units':sum(len(r['rows']) for r in data['results']),
        'scanned_unit_label_pairs':sum(r['joint_keyword_supplement_coverage']['checked_unit_label_pairs'] for r in data['results']),
        'new_this_invocation':contract.get('new_tags',0),
        'joint_direct_added_pairs':sum(r['joint_keyword_supplement_coverage']['direct_added_pairs'] for r in data['results']),
        'joint_review_pairs':sum(r['joint_keyword_supplement_coverage']['review_pairs'] for r in data['results']),
        'label_only_not_added_pairs':sum(r['joint_keyword_supplement_coverage']['label_only_not_added_pairs'] for r in data['results']),
        'joint_only_candidate_pairs':sum(r['joint_keyword_supplement_coverage'].get('joint_only_candidate_pairs',0) for r in data['results']),
        'api_calls':0,'input_tokens':0,'output_tokens':0,'estimated_yuan':0,'zero_miss_guarantee':False}
    for status,counter in [('new_tags','new_confirmed_tags'),('withdrawn_wrong_tags','withdrawn_wrong_tags'),('restored_units','restored_units')]:
        data['supplement_status'][status]=sum(r['label_supplement_coverage'][counter] for r in data['results'])
    data['supplement_status'].update(deferred_candidates=sum(len(r['label_supplement_deferred']) for r in data['results']),
        sources_with_deferred_candidates=sum(bool(r['label_supplement_deferred']) for r in data['results']))
    for topic,kind in [(core.base.T1,'产品信息单元'),(core.base.T2,'观点信息单元')]:
        data['tables'][kind]=[u for r in data['results'] if r['document']['topic']==topic for u in r['rows']]
    if not (output_dir/'calls').exists():
        data['baseline_token_cost']=copy.deepcopy(data.get('current_run_token_cost'));data.pop('current_run_token_cost',None)
        data['supplement_call_costs']={}
    output_dir.mkdir(parents=True,exist_ok=True)
    core.save_json(output_dir/'delivery_results.json',data)
    core.save_json(output_dir/'joint_keyword_supplement_summary.json',data['joint_keyword_supplement_status'])
    core.save_json(output_dir/'joint_keyword_supplement_verification.json',contract)
    return data['joint_keyword_supplement_status']


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--input',type=Path,required=True);ap.add_argument('--output-dir',type=Path,required=True)
    ap.add_argument('--taxonomy',type=Path,default=core.DEFAULT_TAXONOMY);ap.add_argument('--prior',type=Path)
    a=ap.parse_args();print(json.dumps(apply_file(a.input,a.output_dir,a.taxonomy,a.prior),ensure_ascii=False))
