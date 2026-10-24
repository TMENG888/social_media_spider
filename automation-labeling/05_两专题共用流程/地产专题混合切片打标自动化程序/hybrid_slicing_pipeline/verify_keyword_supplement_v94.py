"""Independently check persisted rule additions, scope, provenance and deltas."""
import argparse
import json
from pathlib import Path
import keyword_supplement_v94 as k


def verify(prior_path,directory,taxonomy_path):
    prior=json.loads(prior_path.read_text(encoding='utf-8'))
    data=json.loads((directory/'delivery_results.json').read_text(encoding='utf-8'))
    taxonomy=k.core.base.load_taxonomy(taxonomy_path)
    report=k.validate(prior,data,taxonomy);added=0;visited=0
    old={r['document']['record_id']:r for r in prior['results']}
    for result in data['results']:
        units={u['unit_id']:u for u in k.core.audit_units(result)}
        index=k.core.index_for(taxonomy,result['document']['topic'])
        c=result['keyword_supplement_coverage']
        assert c['eligible_labels']==len(index)
        assert c['checked_unit_label_pairs']==len(result['rows'])*len(index)
        visited+=c['checked_unit_label_pairs']
        previous={r['unit_id']:r for r in old[result['document']['record_id']]['rows']}
        events={(e['unit_id'],e['key']):e for e in result['keyword_supplement_events'] if e['处理']=='关键词规则直接补标'}
        for row in result['rows']:
            existing={t['标签路径ID'] for t in previous[row['unit_id']]['标签明细']}
            for tag in row['标签明细']:
                if tag['标签路径ID'] in existing:continue
                uid=row['unit_id'];key='D'+tag['标签路径ID'][4:];event=events[(uid,key)]
                assert not event['program_issues'] and event['confidence'] is None
                rule=k.compile_rule(key,index[key]);unit=units[uid]
                hits=k.find_hits(unit,rule)
                assert any(not k.hit_issues(h,rule,unit,old[result['document']['record_id']]) for h in hits)
                for span in event['attribute_spans']+event['keyword_matches']:
                    assert unit['start']<=span['start']<span['end']<=unit['end']
                    assert result['document']['text'][span['start']:span['end']]==span['quote']
                assert tag==k.core.label_json(index[key]);added+=1
        # Resuming must not grow labels, explanations, remarks or audit history.
        again=k.process(result,taxonomy)
        assert again['rows']==result['rows'] and again['keyword_supplement_events']==result['keyword_supplement_events']
    assert added==report.get('new_tags',0)
    assert visited==data['keyword_supplement_status']['scanned_unit_label_pairs']
    report.update(checked_unit_label_pairs=visited,new_keyword_tags=added,
                  idempotent=True,no_api_calls_by_keyword_stage=True,
                  note='核对字典与证据、对象规则、追加和幂等；不代表人工金标准精确率。')
    k.core.save_json(directory/'keyword_supplement_verification.json',report)
    return report


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--prior',type=Path,required=True)
    ap.add_argument('--output-dir',type=Path,required=True);ap.add_argument('--taxonomy',type=Path,default=k.core.DEFAULT_TAXONOMY)
    a=ap.parse_args();print(json.dumps(verify(a.prior,a.output_dir,a.taxonomy),ensure_ascii=False))
