"""Read actual v57 responses without editing results or invoking the API."""
import argparse
import json
from pathlib import Path
import shared_mechanism_protocol_v58 as mechanism
import comment_attribution_feedback_v58 as attribution


def walk(value):
    if isinstance(value,dict):
        yield value
        for child in value.values():yield from walk(child)
    elif isinstance(value,list):
        for child in value:yield from walk(child)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('folder',type=Path)
    parser.add_argument('--output',type=Path,required=True);a=parser.parse_args()
    key='9f54956aaa3de005ac8e3d02e281f848e77297d0ac4a21c5ddc913ab9713b294'
    raw=json.loads((a.folder/'calls'/(key+'.json')).read_text(encoding='utf-8'))
    response=raw['response']
    # Schema enums require only actual keys. No invented text is used as evidence.
    entries=[{'source_unit_key':k} for k in response['member_assertions']]
    structural=mechanism.protocol_issues(response,entries,entries)
    snapshot=json.loads((a.folder/'current_snapshot.json').read_text(encoding='utf-8'))
    result=next(r for r in snapshot['results'] if r['document']['record_id']=='T2-C-7963753211120747268')
    failures=[x for x in walk(result['local_acceptance']) if x.get('accepted') is False and x.get('raw_object_bindings')]
    feedback=attribution.compact_feedback(failures)
    report={'mechanism_request_key':key,'source_record_id':raw['metrics']['record_id'],
            'actual_reason_length':len(response['why']),'actual_protocol_issues':structural,
            'failed_comment_binding_records':len(failures),'compact_failed_links':feedback,
            'checks':{'actual_long_reason_detected':any('文本长度' in x for x in structural),
                      'failed_attribute_keys_retained':bool(feedback) and all(x.get('failed_bindings') for x in feedback)},
            'scope':'仅对实际旧响应重放结构诊断与反馈保留；未调用API、未改交付行，不证明新生成效果。'}
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'checks':report['checks'],'actual_reason_length':report['actual_reason_length'],
                      'failed_comment_binding_records':len(failures)},ensure_ascii=False))
    raise SystemExit(not all(report['checks'].values()))


if __name__=='__main__':main()
