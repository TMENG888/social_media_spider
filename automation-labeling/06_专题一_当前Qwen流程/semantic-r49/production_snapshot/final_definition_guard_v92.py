"""Route unambiguous risk signals in NEW labels to review, never erase sources."""
import argparse,copy,json,re
from pathlib import Path
import full_dictionary_supplement_v92 as s


def final_scope_risks(item,index,doc=None):
    """Flag explicit competing-object evidence; never replace it with a guess.

    These final-review cues only hold NEW candidates for a human. Chinese
    measurement expressions remain valid; absence of an Arabic number is not
    a reason to reject a label.
    """
    issues=s.object_scope_risks(item,index,doc)
    text=''.join(item.get('quotes',[]))
    context=text+''.join(item.get('context_quotes',[]))
    if item['key']=='D0373' and '样板间' in text and not re.search(r'会所|會所|clubhouse',context,re.I):
        issues.append('对象待核：引文描述住宅样板间风格，未确认会所对象，不能自动补会所风格')
    if item['key']=='D0168' and '住宅' in text and not re.search(r'别墅|別墅|叠墅|叠拼|疊墅|疊拼|联排|聯排|独栋|獨棟|双拼|雙拼|院墅|墅居|现墅|現墅',context):
        issues.append('业态待核：引文仅确认住宅，未确认别墅或其具体业态，不能自动补别墅标签')
    if item['key']=='D0403':
        amount=r'(?:[0-9一二两三四五六七八九十百千万零点,，.]+)\s*(?:㎡|m²|m2|平方米|平方公尺|平米|方)'
        club_measure=re.search(amount+r'\s*[^，。；;!?！？]{0,12}(?:会所|會所)',text,re.I)
        landscape_measure=re.search(amount+r'\s*[^，。；;!?！？]{0,8}(?:园林|景观|花园|绿地|绿化)',text,re.I)
        explicit_landscape=re.search(r'(?:园林|景观|花园|绿地|绿化)(?:占地)?面积[^，。；;!?！？]{0,12}'+amount,text,re.I)
        if club_measure and not landscape_measure and not explicit_landscape:
            issues.append('面积对象待核：数值直接对应会所，未定位景观面积，不把会所面积自动转为景观面积')
    return issues


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--prior',type=Path,default=s.DEFAULT_PRIOR)
    ap.add_argument('--taxonomy',type=Path,default=s.DEFAULT_TAXONOMY);ap.add_argument('--output-dir',type=Path,required=True);a=ap.parse_args()
    data=json.loads((a.output_dir/'delivery_results.json').read_text(encoding='utf-8'));prior=json.loads(a.prior.read_text(encoding='utf-8'))
    old={r['document']['record_id']:r for r in prior['results']};tax=s.base.load_taxonomy(a.taxonomy);changes=[]
    for r in data['results']:
        doc=r['document'];index=s.index_for(tax,doc['topic']);units={u['unit_id']:u for u in s.audit_units(r)}
        before={(u['unit_id'],'D'+t['标签路径ID'][4:]) for u in old[doc['record_id']]['rows'] for t in u['标签明细']}
        pending=[];rows=[];traces=[]
        for row,trace in zip(r['rows'],r['traces']):
            for proof in list(trace.get('全字典补选证据',[])):
                pair=(row['unit_id'],proof['key'])
                if pair in before:continue
                risks=final_scope_risks(proof,index,doc)
                if not risks:continue
                tid='VOC-'+proof['key'][1:]
                if not any(t['标签路径ID']==tid for t in row['标签明细']):continue
                event={**proof,'处理':'新增标签必要证据不足转待核','原因':'；'.join(risks),'definition_risk_review':True}
                r['label_supplement_events'].append(event);r['label_supplement_deferred'].append(event)
                row['标签明细']=[t for t in row['标签明细'] if t['标签路径ID']!=tid]
                row['打标说明']='\n'.join(line for line in row['打标说明'].splitlines() if tid not in line)
                row['备注']+='；'+event['原因'];trace['全字典补选证据'].remove(proof)
                trace.setdefault('补选必要证据待核',[]).append(proof);changes.append({'unit_id':row['unit_id'],'标签':tid,'原因':event['原因']})
            if row['标签明细']:rows.append(row);traces.append(trace)
            else:
                u=units[row['unit_id']];pending.append({'unit_id':row['unit_id'],'record_id':doc['record_id'],'来源类型':doc['kind'],
                    '原文':u['text'],'起点':u['start'],'终点':u['end'],'原因':'新增标签必要证据不足，原文范围保留待核','旧单元':row,'补全候选':None,'校验':None})
        r['rows']=rows;r['traces']=traces;r['pending_units']+=pending
        r['label_supplement_deferred']=s.unique_deferred(r['label_supplement_deferred'])
        c=r['label_supplement_coverage'];c['deferred_candidate_count']=len(r['label_supplement_deferred'])
        c['new_confirmed_tags']=sum((u['unit_id'],'D'+t['标签路径ID'][4:]) not in before for u in rows for t in u['标签明细'])
        oldids={u['unit_id'] for u in old[doc['record_id']]['rows']};c['restored_units']=sum(u['unit_id'] not in oldids for u in rows)
        c['all_candidates_adjudicated']=not c['errors'] and not r['label_supplement_deferred'] and not c['remaining_facts'] and not r['pending_units']
        r['complete']=bool(r['complete'] and c['all_candidates_adjudicated'])
        risk_pairs={(e['unit_id'],e['key']) for e in r['label_supplement_events'] if e.get('definition_risk_review') or e['处理'].startswith('新增标签专项')}
        present={(u['unit_id'],'D'+t['标签路径ID'][4:]) for u in rows for t in u['标签明细']}
        c['risk_reviewed_new_candidates']=len(risk_pairs);c['risk_held_new_candidates']=len(risk_pairs-present)
        r['definition_risk_review_applied'].update(checked_new_candidates=len(risk_pairs),held_new_candidates=len(risk_pairs-present))
    s.validate_contract(prior,data['results'],tax)
    for name,field in [('new_tags','new_confirmed_tags'),('restored_units','restored_units')]:data['supplement_status'][name]=sum(r['label_supplement_coverage'][field] for r in data['results'])
    data['supplement_status']['deferred_candidates']=sum(len(r['label_supplement_deferred']) for r in data['results'])
    data['supplement_status']['sources_with_deferred_candidates']=sum(bool(r['label_supplement_deferred']) for r in data['results'])
    history=list({(e['unit_id'],e['key']):{'unit_id':e['unit_id'],'标签':'VOC-'+e['key'][1:],'原因':e['原因']}
        for r in data['results'] for e in r['label_supplement_events'] if e['处理']=='新增标签必要证据不足转待核'}.values())
    data['supplement_status']['final_evidence_guard_held']=len(history)
    data['supplement_status']['risk_reviewed_new_candidates']=sum(r['label_supplement_coverage']['risk_reviewed_new_candidates'] for r in data['results'])
    data['supplement_status']['risk_held_new_candidates']=sum(r['label_supplement_coverage']['risk_held_new_candidates'] for r in data['results'])
    for topic,kind in [(s.base.T1,'产品信息单元'),(s.base.T2,'观点信息单元')]:data['tables'][kind]=[u for r in data['results'] if r['document']['topic']==topic for u in r['rows']]
    s.save_json(a.output_dir/'final_definition_guard.json',{'held':history,'scope':'只将新增的必要证据不足候选送人工，不重新投票、不删除原文、不改变旧合法标签'})
    s.save_json(a.output_dir/'delivery_results.json',data);print(json.dumps({'held':changes,'status':data['supplement_status']},ensure_ascii=False))


if __name__=='__main__':main()
