"""Read-only batch reconciliation and review inventory; no tag editing."""
import argparse,collections,hashlib,json,sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf8')
ROOT=Path(__file__).parent
p=argparse.ArgumentParser();p.add_argument('--count',type=int,choices=[10,500],default=10);args=p.parse_args();count=args.count
raw=json.loads((ROOT/f'results_{count}.json').read_text(encoding='utf8'))
assert len(raw)==count and len({r['document']['source_id'] for r in raw})==count
inventory=[]
for result in raw:
    doc=result['document'];units=result['semantic_partition'];pos=0
    for u in units:
        assert u['start']==pos and u['end']>pos and u['text']==doc['text'][pos:u['end']]
        pos=u['end']
        assert len({p['tag_id'] for p in u['labels']})==len(u['labels'])
        for p in u['labels']:assert p['quote'] in u['text'] and p['quote'] and p['reason']
    assert pos==len(doc['text'])
    assert len({(u['start'],u['end']) for u in units})==len(units)
    inventory.append({'source_id':doc['source_id'],'title':doc['title'],'platform':doc['row']['平台'],
        'full_partition_units':len(units),'tagged_units':sum(bool(u['labels']) for u in units),
        'tag_count':sum(len(u['labels']) for u in units),
        'rows':[{'excerpt':r['原文摘录'],'tags':r['标签明细'],'practice':r['具体产品做法'],'brand':r['品牌组'],'entity':r['经营主体'],'city':r['城市']} for r in result['rows'] if r['标签明细']]})
report={'processed_articles':count,'remaining_490_started':count==500,'articles_with_labels':sum(v['tagged_units']>0 for v in inventory),
        'tagged_slices':sum(v['tagged_units'] for v in inventory),'full_partition_slices':sum(v['full_partition_units'] for v in inventory),
        'tag_assignments':sum(v['tag_count'] for v in inventory),'articles':inventory,
        'assessment':'结构和原文证据核验，不等于逐条人工语义准确率验收。'}
(ROOT/('trial_audit.json' if count==10 else 'batch_audit.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({k:v for k,v in report.items() if k!='articles'},ensure_ascii=False))
