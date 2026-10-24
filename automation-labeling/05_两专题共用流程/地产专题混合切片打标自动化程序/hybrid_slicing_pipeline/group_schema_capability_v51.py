"""One read-only-source real API schema capability probe, no delivery edits."""
import argparse
import json
from pathlib import Path
import delivery_v4 as base
import final_boundary_closure_v47 as closing
import source_only_group_recovery_v50 as recovery
import group_response_schema_v51 as contract


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--sample',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True);args=parser.parse_args()
    sample=json.loads(args.sample.read_text(encoding='utf-8'))
    doc=next(d for d in sample['documents'] if d['record_id']=='T1-182247585093626012')
    text=doc['text']
    a=text.index('其实咱们上一次说了这个卫生间味道之后')
    b=text.index('可以，这个问题我们是通过两个方案来解决',a)
    c=text.index('我好害怕',b)
    entries=[{'source_unit_key':'CAP-FRAME','start':a,'end':b,'text':text[a:b]},
             {'source_unit_key':'CAP-FACTS','start':b,'end':c,'text':text[b:c]}]
    requested=contract.schema(entries,entries)
    runner=base.ApiRunner(args.output_dir,10)
    response,m=runner.call(closing.GROUP_SYSTEM+recovery.INSTRUCTION+contract.INSTRUCTION,
        {'source_text':text,'unit_catalog':entries,'group_members':entries,'topic':doc['topic']},doc,
        '原API受约束JSON能力核验-v11.51',response_schema=requested)
    missing=sorted(set(requested['required'])-set(response)) if isinstance(response,dict) else list(requested['required'])
    report={'response':response,'metrics':m,'missing_required_keys':missing,
            'passed':m['status']=='success' and not missing,
            'scope':'仅原API的受约束JSON响应能力和当前组响应，不证明整篇切片或打标准确率'}
    base.save_json(args.output_dir/'capability_report.json',report)
    print(base.dumps({'status':m['status'],'http_status':m['http_status'],'missing_required_keys':missing,
                     'tokens':m['total_tokens'],'estimated_yuan':m['estimated_yuan'],'passed':report['passed']}))
    raise SystemExit(not report['passed'])
