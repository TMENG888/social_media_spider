"""Fresh seeded channel sample, complete comments; original sources read only."""
import argparse
import copy
import json
import os
import random
from collections import defaultdict
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import delivery_v8 as p

POST=Path('C:/Users/YS-Insight/Desktop/ods_social_media_post.csv')
COMMENT=Path('C:/Users/YS-Insight/Desktop/ods_social_media_comment.csv')


def fresh_sample(posts,comments,business,excluded,seed=20261009):
    rng=random.Random(seed);index=p.base.PostIndex(posts);linked=defaultdict(list);mapping=[]
    for c in comments:
        parent,status=index.map_comment(c)
        if parent and parent.get('项目')==p.base.T2 and (not c.get('项目') or c['项目']==p.base.T2):
            linked[parent['id']].append(c)
        elif status not in {'无可用映射键'}:mapping.append({'评论ODS主键':c['id'],'状态':status})
    selected=[];coverage=[]
    quotas={p.base.T1:{'微信公众号':3,'小红书':3,'微信视频号':3,'网页':3},
            p.base.T2:{'微信公众号':3,'小红书':3,'网页':3}}
    for topic,channels in quotas.items():
        for channel,n in channels.items():
            raw=[r for r in posts if r.get('项目')==topic and r.get('平台')==channel]
            eligible=[r for r in raw if r['id'] not in excluded and p.base.choose_source(r)[1]]
            if topic==p.base.T2 and channel=='小红书':eligible=[r for r in eligible if linked[r['id']]]
            def strata(row):
                nchar=len(p.base.choose_source(row)[1])
                return '短' if nchar<1200 else '中' if nchar<4200 else '长'
            picked=p.base.stratified_pick(eligible,n,rng,strata)
            selected.extend((r,'新随机渠道样本') for r in picked)
            coverage.append({'专题':topic,'平台':channel,'原始文章数':len(raw),
                '可用主体数':sum(bool(p.base.choose_source(r)[1]) for r in raw),
                '排除旧批后可抽样数':len(eligible),'渠道覆盖抽样数':n})
    selected_ids={r['id'] for r,stage in selected}
    more=[r for r in posts if r.get('项目')==p.base.T2 and r['id'] not in excluded|selected_ids
          and linked[r['id']] and p.base.choose_source(r)[1]]
    selected.extend((r,'有评论随机补样') for r in rng.sample(sorted(more,key=lambda r:r['id']),3))
    docs=[];manifest=[]
    for row,stage in selected:
        field,text=p.base.choose_source(row)
        docs.append(p.base.make_document(row,'文章',row,field,text))
        manifest.append({'专题':row['项目'],'平台':row['平台'],'源文章ODS主键':row['id'],
            '抽样用途':stage,'主体字段':field,'字符数':len(text),'关联评论数':len(linked[row['id']]),
            '项目候选线索':p.base.project_hints(row,business['projects'])})
        if row['项目']==p.base.T2:
            for c in sorted(linked[row['id']],key=lambda c:c['id']):
                docs.append(p.base.make_document(c,'评论',row,'评论内容',c.get('评论内容') or ''))
    if len({d['record_id'] for d in docs})!=len(docs):raise ValueError('Duplicate source identifiers')
    for channel in {'微信视频号'}-set(quotas[p.base.T2]):
        raw=[r for r in posts if r.get('项目')==p.base.T2 and r.get('平台')==channel]
        coverage.append({'专题':p.base.T2,'平台':channel,'原始文章数':len(raw),
            '可用主体数':sum(bool(p.base.choose_source(r)[1]) for r in raw),'渠道覆盖抽样数':0,
            '说明':'无可用主体，单独报告缺口' if not any(p.base.choose_source(r)[1] for r in raw) else '本次未设配额'})
    return docs,{'seed':seed,'samples':manifest,'coverage':coverage,'comment_mapping_issues':mapping,
                 'fresh_articles_excluding_previous_batch':True}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--prepare-only',action='store_true');args=parser.parse_args()
    baseline=json.loads(Path('test_results_v8_integrated_20261009_api/delivery_results.json').read_text(encoding='utf-8'))
    excluded={r['document']['source_id'] for r in baseline['results'] if r['document']['kind']=='文章'}
    business=p.base.load_business();taxonomy=p.base.load_taxonomy(p.v.legacy.TAXONOMY)
    docs,sampling=fresh_sample(p.base.read_csv(POST),p.base.read_csv(COMMENT),business,excluded)
    p.base.save_json(args.output_dir/'fresh_sample.json',{'documents':docs,'sampling':sampling})
    print(p.base.dumps({'articles':sum(d['kind']=='文章' for d in docs),'comments':sum(d['kind']=='评论' for d in docs),
                       'seed':sampling['seed'],'old_article_overlap':sum(d['source_id'] in excluded for d in docs if d['kind']=='文章')}),flush=True)
    if args.prepare_only:return
    runner=p.base.ApiRunner(args.output_dir,10,key=os.getenv('YS_LLM_API_KEY'))
    signature=p.base.digest({'module':'random-acceptance-v10-v8-baseline-1','taxonomy':taxonomy,'business':business,
                            'system':p.GROUND_SYSTEM})
    def work(doc):
        file=args.output_dir/'documents'/(p.base.digest({'signature':signature,'document':doc})+'.json')
        if file.exists():
            saved=json.loads(file.read_text(encoding='utf-8'))
            if saved.get('complete'):return saved
        try:
            result=p.process_document(doc,taxonomy,business,runner)
        except (ValueError,TypeError,KeyError,IndexError,AttributeError) as exc:
            # Preserve this source and all call evidence; no invented delivery
            # row, empty success, or silent replacement sample on API failure.
            reason='响应结构异常：'+type(exc).__name__+' '+str(exc)
            result={'document':doc,'rows':[],'traces':[],
                    'audit':[{'原因':reason,'需人工审核':True,'原文':doc['text']}],
                    'complete':False,'calls':[c for c in runner.calls if c['record_id']==doc['record_id']],
                    'coverage_issues':[reason],'grounding_issues':[reason]}
        p.base.save_json(file,result);return result
    results=[]
    with ThreadPoolExecutor(max_workers=10) as pool:
        for f in as_completed([pool.submit(work,d) for d in docs]):
            results.append(f.result());print(p.base.dumps({'completed_sources':len(results),'planned_sources':len(docs)}),flush=True)
    order={d['record_id']:i for i,d in enumerate(docs)};results.sort(key=lambda r:order[r['document']['record_id']])
    p.v.legacy.reconcile_parent_relevance(results,business)
    data=p.base.export(args.output_dir,results,sampling,taxonomy,business,runner,'api',all(r['complete'] for r in results))
    data['summary'].update(version=p.VERSION,random_acceptance_seed=sampling['seed'],
        planned_articles=sum(d['kind']=='文章' for d in docs),
        mapping_contract='映射文章id=评论源表文章id；所属父文章ODS主键单独追溯',
        catalogue_counts={topic:len(p.v.registry(taxonomy,topic)) for topic in (p.base.T1,p.base.T2)},
        note='新随机样本的待验收基线；尚需语义粒度、重复事实及局部标签覆盖复核。')
    p.v.expose_unknown_totals(data)
    p.base.save_json(args.output_dir/'delivery_results.json',data)
    print(p.base.dumps(data['summary']),flush=True)


if __name__=='__main__':main()
