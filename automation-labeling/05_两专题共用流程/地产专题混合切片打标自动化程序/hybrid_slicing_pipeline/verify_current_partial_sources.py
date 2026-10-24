"""Reconcile all requested sources and completed subset without claiming completion."""
import argparse
import json
from pathlib import Path
import verify_original_csv_sources as original


def main():
    p=argparse.ArgumentParser();p.add_argument('--sample',type=Path,required=True)
    p.add_argument('--documents',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    sample=json.loads(args.sample.read_text(encoding='utf-8'))
    requested={d['record_id']:d for d in sample['documents']}
    report=original.inspect({'results':[{'document':d} for d in sample['documents']]},
                            original.base.read_csv(original.POST),original.base.read_csv(original.COMMENT))
    completed=[json.loads(f.read_text(encoding='utf-8')) for f in args.documents.glob('*.json')]
    fields=('record_id','source_id','kind','topic','field','text','parent','row')
    source_checks=[];seen=set()
    for r in completed:
        doc=r['document'];rid=doc['record_id'];expected=requested.get(rid)
        differences=[k for k in fields if expected is None or doc.get(k)!=expected.get(k)]
        if rid in seen:differences.append('duplicate_record_id')
        seen.add(rid)
        source_checks.append({'record_id':rid,'passed':not differences,'differences':differences})
        if differences:report['errors'].append({'record_id':rid,'requirement':'完成来源与固定请求源一致','differences':differences})
    report.update(completed_sources=len(completed),planned_sources=len(requested),
                  completed_source_checks=source_checks,pending_sources=sorted(set(requested)-seen),
                  scope='全部请求源与当前原CSV核对；已完成来源与请求全文核对。部分结果，不证明本批执行完成或语义质量')
    original.base.save_json(args.output,report)
    print(original.base.dumps({k:report[k] for k in ('checked_sources','completed_sources','planned_sources','expected_comments','errors')}))
    raise SystemExit(bool(report['errors']))


if __name__=='__main__':main()
