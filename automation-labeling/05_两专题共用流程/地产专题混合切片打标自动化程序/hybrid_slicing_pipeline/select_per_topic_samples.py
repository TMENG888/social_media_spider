"""Select a reproducible stratified sample from each of the two exact topics."""
import argparse
import csv
import json
import random
from collections import defaultdict, Counter
from pathlib import Path
from multilabel_v2 import T1 as TOPIC1, T2 as TOPIC2, choose_source

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--base-config',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--per-topic',type=int,default=50)
    parser.add_argument('--seed',type=int,default=20261008)
    args=parser.parse_args()
    if args.per_topic<1: parser.error('--per-topic must be positive')
    config=json.loads(args.base_config.read_text(encoding='utf-8'))
    with args.input.open(encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
    rng=random.Random(args.seed); selected=[]; metadata={}; population={}
    for topic in [TOPIC1,TOPIC2]:
        groups=defaultdict(list)
        eligible=[r for r in rows if r.get('项目')==topic and choose_source(r)[1]]
        population[topic]=len(eligible)
        if len(eligible)<args.per_topic: raise ValueError(f'{topic}: only {len(eligible)} eligible articles')
        for r in eligible:
            source,text=choose_source(r)
            length='短文' if len(text)<1200 else '中长文' if len(text)<4200 else '长文'
            groups[(r.get('平台',''),r.get('内容类型',''),length,source)].append(r)
        quotas={k:len(v)*args.per_topic/len(eligible) for k,v in groups.items()}
        allocated={k:int(v) for k,v in quotas.items()}
        remaining=args.per_topic-sum(allocated.values())
        for k in sorted(groups,key=lambda k:(-(quotas[k]-allocated[k]),k))[:remaining]: allocated[k]+=1
        picked=[]
        for k in sorted(groups): picked.extend(rng.sample(sorted(groups[k],key=lambda r:str(r['id'])),allocated[k]))
        selected.extend(picked)
        for r in picked:
            source,text=choose_source(r)
            metadata[str(r['id'])]={'专题':topic,'平台':r.get('平台'),'内容类型':r.get('内容类型'),'切片来源':source,'来源字符数':len(text)}
    ids=[str(r['id']) for r in selected]
    if len(set(ids))!=len(ids): raise ValueError('Source has repeated id values')
    config.update(sample_ids=ids,sample_metadata=metadata,sampling_seed=args.seed,per_topic=args.per_topic,concurrency=4)
    # Do not carry obsolete article-specific project overrides into new samples.
    config['topic1_project_overrides']={k:v for k,v in config.get('topic1_project_overrides',{}).items() if k in ids}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'eligible_population':population,'selected':dict(Counter(r['项目'] for r in selected)),'seed':args.seed},ensure_ascii=False))

if __name__=='__main__': main()
