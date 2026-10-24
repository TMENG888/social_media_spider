"""Limited reference-anchor evaluation, never a dataset-wide accuracy claim."""
import argparse,json
from pathlib import Path

def evaluate(data,reference,dictionary_ids=None):
    records={r['document']['record_id']:r for r in data.get('results',[])}
    report=[];errors=[];present_positive=hit_positive=present_negative=violations=0
    for a in reference['anchors']:
        r=records.get(a['record_id'])
        entry=dict(a,source_present=r is not None)
        if r is None:
            entry.update(status='来源未完成',missing_required=None,forbidden_hits=None)
            report.append(entry);continue
        evidence_quotes=[a['quote']]+a.get('equivalent_quotes',[])
        if any(q not in r['document']['text'] for q in evidence_quotes):
            errors.append({'record_id':a['record_id'],'error':'参考引文不在原始主体','quote':a['quote']})
            entry['status']='参考证据不合法';report.append(entry);continue
        if dictionary_ids is not None and any(t not in dictionary_ids for t in a['required']+a['forbidden']):
            errors.append({'record_id':a['record_id'],'error':'参考标签不在当前字典'})
            entry['status']='参考标签不合法';report.append(entry);continue
        rows=[u for u in r['rows'] if any(q in u.get('原文摘录',u.get('原始摘录','')) for q in evidence_quotes)]
        selected={t['标签路径ID'] for u in rows for t in u['标签明细']}
        missing=set(a['required'])-selected;bad=set(a['forbidden'])&selected
        present_positive+=len(a['required']);hit_positive+=len(set(a['required'])&selected)
        present_negative+=len(a['forbidden']);violations+=len(bad)
        entry.update(status='通过' if not missing and not bad else '未通过',matched_units=[u['unit_id'] for u in rows],
                     missing_required=sorted(missing),forbidden_hits=sorted(bad))
        report.append(entry)
    return {'reference_type':reference['reference_type'],'anchors':report,'reference_errors':errors,
        'planned_anchors':len(report),'processed_anchors':sum(x['source_present'] for x in report),
        'unprocessed_anchors':sum(not x['source_present'] for x in report),
        'processed_required_tags':present_positive,'hit_required_tags':hit_positive,
        'missed_required_tags':present_positive-hit_positive,
        'processed_forbidden_checks':present_negative,'forbidden_tag_hits':violations,
        'processed_positive_anchor_recall':hit_positive/present_positive if present_positive else None,
        'note':'仅对已完成来源中的明确参考锚点计算；未完成来源单列，不计成功。其他未审标签不算正确或错误，不能据此宣称全样本精确率/召回率。'}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('input',type=Path);p.add_argument('--output',required=True,type=Path)
    a=p.parse_args();import delivery_v11 as v
    ref=json.loads(Path(__file__).with_name('independent_label_anchors_v59.json').read_text(encoding='utf-8'))
    ids={x['tag_id'] for x in v.p.base.load_taxonomy(v.p.v.legacy.TAXONOMY)}
    r=evaluate(json.loads(a.input.read_text(encoding='utf-8')),ref,ids)
    v.p.base.save_json(a.output,r)
    print(v.p.base.dumps({k:r[k] for k in ('planned_anchors','processed_anchors','unprocessed_anchors','processed_required_tags',
        'hit_required_tags','missed_required_tags','processed_forbidden_checks','forbidden_tag_hits','reference_errors')}))
    raise SystemExit(bool(r['reference_errors']))
