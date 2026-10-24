"""Persisted joint candidates/additions and additive/frozen contracts."""
import argparse
import json
from pathlib import Path
import joint_keyword_supplement_v95 as j


def verify(prior_path,directory,taxonomy_path):
    prior=json.loads(prior_path.read_text(encoding='utf-8'))
    data=json.loads((directory/'delivery_results.json').read_text(encoding='utf-8'))
    taxonomy=j.core.base.load_taxonomy(taxonomy_path);report=j.k.validate(prior,data,taxonomy)
    old={r['document']['record_id']:r for r in prior['results']};joint_added=0;raw_added=0;visited=0
    for result in data['results']:
        previous=old[result['document']['record_id']]
        units={u['unit_id']:u for u in j.core.audit_units(result)}
        index=j.core.index_for(taxonomy,result['document']['topic'])
        traces={t['unit_id']:t for t in result['traces']}
        original_rows={r['unit_id']:r for r in previous['rows']}
        events={(e['unit_id'],e['key']):e for e in result['joint_keyword_supplement_events'] if not e['program_issues']}
        c=result['joint_keyword_supplement_coverage'];assert c['eligible_labels']==len(index)
        assert c['checked_unit_label_pairs']==len(result['rows'])*len(index);visited+=c['checked_unit_label_pairs']
        for row in result['rows']:
            uid=row['unit_id'];unit=units[uid];frozen=traces[uid]['联合补标初始标签快照']
            existing={t['标签路径ID'] for t in original_rows[uid]['标签明细']}
            for tag in row['标签明细']:
                if tag['标签路径ID'] in existing:continue
                key='D'+tag['标签路径ID'][4:];rule=j.k.compile_rule(key,index[key])
                assert tag==j.core.label_json(index[key])
                if (uid,key) not in events:
                    assert any(not j.k.hit_issues(h,rule,unit,previous) for h in j.k.find_hits(unit,rule));raw_added+=1;continue
                event=events[(uid,key)]
                assert event['source_label_id'] in {t['标签路径ID'] for t in frozen}
                candidates=j.inherited_hits(unit,rule,frozen,traces[uid],index,previous)
                assert any(not j.inherited_issues(h,rule,unit,previous) for h in candidates)
                assert event['confidence'] is None
                for span in event['attribute_spans']+event['object_spans']+event['keyword_matches']:
                    assert unit['start']<=span['start']<span['end']<=unit['end']
                    assert result['document']['text'][span['start']:span['end']]==span['quote']
                joint_added+=1
        again=j.process(result,taxonomy)
        assert again['rows']==result['rows']
        assert again['joint_keyword_supplement_events']==result['joint_keyword_supplement_events']
    assert visited==data['joint_keyword_supplement_status']['scanned_unit_label_pairs']
    assert joint_added+raw_added==report.get('new_tags',0)
    report.update(new_joint_tags=joint_added,new_raw_tags=raw_added,checked_unit_label_pairs=visited,
        frozen_no_cascade=True,idempotent=True,no_api_calls=True,
        note='字典、原文证据、旧字段保护及幂等检查通过，不等同于人工金标准准确率')
    j.core.save_json(directory/'joint_keyword_supplement_verification.json',report)
    return report


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--prior',type=Path,required=True);ap.add_argument('--output-dir',type=Path,required=True)
    ap.add_argument('--taxonomy',type=Path,default=j.core.DEFAULT_TAXONOMY)
    a=ap.parse_args();print(json.dumps(verify(a.prior,a.output_dir,a.taxonomy),ensure_ascii=False))
