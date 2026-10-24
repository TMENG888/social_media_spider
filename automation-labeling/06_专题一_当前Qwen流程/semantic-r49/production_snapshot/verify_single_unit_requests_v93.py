"""Read actual call diagnostics and complete per-unit dictionary coverage."""
import argparse
import json
from pathlib import Path
import full_dictionary_supplement_v92 as s


def verify(directory):
    data=json.loads((directory/'delivery_results.json').read_text(encoding='utf-8'));checked=0;calls=0;failed=0
    all_units={u['unit_id']:u for result in data['results'] for u in s.audit_units(result)}
    for result in data['results']:
        coverage=result['label_supplement_coverage'];units=s.audit_units(result)
        assert coverage['request_mode']=='single_unit' and coverage['max_target_units_per_request']==1
        assert coverage['scan_request_count']==len(units)*coverage['branch_count']
        seen=set()
        for scan in result['label_supplement_scans']:
            assert len(scan['unit_ids'])==1
            pair=(scan['unit_ids'][0],scan['branch_number']);assert pair not in seen;seen.add(pair)
            if scan['errors'] or not scan['raw']:failed+=1
            checked+=1
        assert seen=={(u['unit_id'],n) for u in units for n in range(coverage['branch_count'])}
    for path in (directory/'calls').glob('*.json'):
        metrics=json.loads(path.read_text(encoding='utf-8'))['metrics']
        if metrics['phase'].startswith('紧凑'):
            assert metrics['request_scope']=='single_unit' and metrics['target_unit_count']==1
            assert metrics['identity_context_chars']<=1200 and metrics['branch_label_count']<=48
            assert metrics['target_chars']==len(all_units[metrics['target_unit_id']]['text'])
            calls+=1
    contract_errors=data['supplement_status']['sources_with_api_contract_errors']
    report={'passed':failed==0 and contract_errors==0,'sources':len(data['results']),'checked_unit_group_pairs':checked,
        'single_unit_call_records':calls,'failed_scan_pairs':failed,
        'sources_with_api_contract_errors':contract_errors,
        'note':'Verifies isolated request scope and exhaustive dictionary traversal, not semantic accuracy.'}
    s.save_json(directory/'single_unit_request_verification.json',report)
    assert report['passed'],report
    return report


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output-dir',type=Path,required=True);args=ap.parse_args()
    print(json.dumps(verify(args.output_dir),ensure_ascii=False))
