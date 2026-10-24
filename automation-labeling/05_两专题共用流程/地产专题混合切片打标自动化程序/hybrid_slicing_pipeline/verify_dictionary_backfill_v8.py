"""Independent exact check of all delivered tag paths against the VOC file."""
import argparse
import json
import re
from pathlib import Path
import delivery_v8 as p


def verify(data,dictionary):
    errors=[];count=0;missing_source_number=set()
    topics={row['unit_id']:result['document']['topic'] for result in data.get('results',[])
            for row in result['rows']}
    if 'tables' in data:
        groups=[data['tables'][table] for table in ['产品信息单元','观点信息单元']]
    else:
        groups=[result['rows'] for result in data['results']]
    for units in groups:
        for unit in units:
            for tag in unit['标签明细']:
                count+=1;original=dictionary.get(tag['标签路径ID'])
                if original is None:
                    errors.append({'unit_id':unit['unit_id'],'reason':'无字典ID'});continue
                topic=topics.get(unit['unit_id'])
                if topic is not None and topic not in original.get('topics',[]):
                    errors.append({'unit_id':unit['unit_id'],'reason':'标签不适用于当前专题',
                                   'tag_id':original['tag_id'],'topic':topic})
                expected={f'{level}级标签':original.get('l'+str(i)) or None
                    for i,level in enumerate(['一','二','三','四','五'],1)}
                number=original.get('source_number')
                if number in (None,''):number=None;missing_source_number.add(original['tag_id'])
                elif re.fullmatch(r'\d+',str(number)):number=int(number)
                expected.update({'标签路径ID':original['tag_id'],'标签编号':number,
                    '标签强调方向':original['emphasis']})
                if tag!=expected:errors.append({'unit_id':unit['unit_id'],'actual':tag,'expected':expected})
    report={'checked_delivered_tags':count,'checked_sources':len(data.get('results',[])),
        'verification_scope':'完整交付数据' if 'tables' in data else '当前签名快照已完成来源（非全批完成证明）',
        'errors':errors,'dictionary_tags_without_source_number':sorted(missing_source_number),
        'note':'核查字典ID、编号、五级路径、强调方向的精确回填；不证明标签的语义选择正确。'}
    return report


def main():
    parser=argparse.ArgumentParser();parser.add_argument('input',type=Path)
    parser.add_argument('--output',type=Path);args=parser.parse_args()
    data=json.loads(args.input.read_text(encoding='utf-8'))
    dictionary={t['tag_id']:t for t in p.base.load_taxonomy(p.v.legacy.TAXONOMY)}
    report=verify(data,dictionary)
    p.base.save_json(args.output or args.input.parent/'dictionary_backfill_verification.json',report)
    print(p.base.dumps(report))
    if report['errors']:raise SystemExit(1)


if __name__=='__main__':main()
