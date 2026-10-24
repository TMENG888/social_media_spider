"""Read-only inventory for the eventual 300-article topic1 batch."""
import sys,csv,json,collections
from pathlib import Path
sys.dont_write_bytecode=True
sys.stdout.reconfigure(encoding='utf8')
R=Path(__file__).parent
sys.path.insert(0,str(R/'production_snapshot'))
import delivery_v4 as b
raw=Path('C:/Users/YS-Insight/Desktop/专题数据/ods_social_media_post_01.csv')
with raw.open(encoding='utf-8-sig',newline='') as f:
    records=list(csv.DictReader(f))
eligible=[r for r in records if r.get('项目')==b.T1 and b.choose_source(r)[1]]
print(json.dumps({'fields':list(records[0]),'topic1_usable':len(eligible),
 'platforms':dict(collections.Counter(r.get('平台') for r in eligible)),
 'source_fields':dict(collections.Counter(b.choose_source(r)[0] for r in eligible)),
 'brand_metadata':dict(collections.Counter(r.get('品牌名称') for r in eligible)),
 'keywords':dict(collections.Counter(r.get('关键词') for r in eligible).most_common(18)),
 'lengths':dict(collections.Counter('short' if len(b.choose_source(r)[1])<1200 else 'medium' if len(b.choose_source(r)[1])<4200 else 'long' for r in eligible))},ensure_ascii=False))
