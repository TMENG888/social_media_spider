"""Prepare, but do not run, a reproducible fresh topic1 batch.

Collection keywords stratify sampling only; never become labeling answers.
"""
import sys,csv,json,random,re,hashlib,collections
from pathlib import Path
sys.dont_write_bytecode=True;sys.stdout.reconfigure(encoding='utf8')
R=Path(__file__).parent
sys.path.insert(0,str(R/'production_snapshot'))
import delivery_v4 as api
RAW=Path('C:/Users/YS-Insight/Desktop/专题数据/ods_social_media_post_01.csv')
SEED=20261022
ALIASES={'中海':['中海','中国海外宏洋','中国海外发展'],'保利':['保利'],'招商':['招商'],'金茂':['金茂']}
def norm(s):return re.sub(r'\s+','',s)
def prepare():
    refs=[d for b in 'ABC' for d in json.loads((R/'inputs'/f'{b}_documents.json').read_text(encoding='utf8'))]
    excluded_ids={d['source_id'] for d in refs};excluded_texts={norm(d['text']) for d in refs}
    with RAW.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    buckets=collections.defaultdict(list);seen_text=set(excluded_texts);seen_links=set();audit=collections.Counter()
    for row in sorted(rows,key=lambda x:str(x['id'])):
        if row.get('项目')!=api.T1:continue
        field,text=api.choose_source(row)
        if str(row['id']) in excluded_ids or len(text.strip())<80:audit['reference_or_short']+=1;continue
        key=norm(text);url=str(row.get('文章链接') or '')
        if key in seen_text or (api.useful(url) and url in seen_links):audit['duplicate_body_or_url']+=1;continue
        brands=[brand for brand,aliases in ALIASES.items() if any(a in str(row.get('关键词','')) for a in aliases)]
        if len(brands)!=1:audit['ambiguous_collection_keyword']+=1;continue
        seen_text.add(key)
        if api.useful(url):seen_links.add(url)
        length='short' if len(text)<1200 else 'medium' if len(text)<4200 else 'long'
        buckets[brands[0],row.get('平台',''),length].append(api.make_document(row,'文章',row,field,text))
    rng=random.Random(SEED);picked=[]
    for brand in ALIASES:
        # Round-robin channel/length strata, not semantic-answer-based ranking.
        groups={k:v.copy() for k,v in buckets.items() if k[0]==brand}
        for v in groups.values():rng.shuffle(v)
        keys=sorted(groups);count=0
        while count<75:
            progressed=False
            for key in keys:
                if groups[key] and count<75:
                    d=groups[key].pop();d['sampling_stratum']={'collection_brand_hint':key[0],'platform':key[1],'length':key[2]}
                    picked.append(d);count+=1;progressed=True
            if not progressed:raise ValueError('Insufficient unique fresh source candidates for '+brand)
    assert len(picked)==len({d['source_id'] for d in picked})==300
    assert not excluded_ids.intersection(d['source_id'] for d in picked)
    rng.shuffle(picked)
    dest=R/'batch300';dest.mkdir(exist_ok=True)
    payload={'seed':SEED,'source_csv':str(RAW),'source_sha256':hashlib.sha256(RAW.read_bytes()).hexdigest(),
      'planned_articles':300,'started':False,'sampling':'四个采集品牌线索各75；平台及长度分层轮取；去重后排除A/B/C来源及相同正文。关键词只作抽样线索，不作为品牌标注答案。',
      'platforms':dict(collections.Counter(d['row'].get('平台') for d in picked)),
      'brand_hints':dict(collections.Counter(d['sampling_stratum']['collection_brand_hint'] for d in picked)),
      'lengths':dict(collections.Counter(d['sampling_stratum']['length'] for d in picked)),
      'exclusions':dict(audit),'document_count':len(picked)}
    for name,data in [('documents.json',picked),('selection_manifest.json',payload)]:
        (dest/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(payload,ensure_ascii=False))
if __name__=='__main__':prepare()
