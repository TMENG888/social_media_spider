"""Reproducible 500+500 source selection with all uniquely linked T2 comments."""
import argparse,random,copy,json
from collections import defaultdict,Counter
from pathlib import Path
import delivery_v4 as b
from gym_policy_v96 import INSTRUCTION,VERSION

def prepare(posts,comments,business,seed=20261008):
    if len({r['id'] for r in posts})!=len(posts) or len({r['id'] for r in comments})!=len(comments):
        raise ValueError('Repeated ODS primary key')
    idx=b.PostIndex(posts);linked=defaultdict(list);seen=set();mapping=[]
    for c in comments:
        p,status=idx.map_comment(c)
        if not p or p.get('项目')!=b.T2 or c.get('项目') not in ('',None,b.T2):
            mapping.append({'评论ODS主键':c['id'],'状态':status if not p else '专题不符','原文':c.get('评论内容')});continue
        key=(c.get('平台'),p['id'],c.get('评论id') or c['id'])
        if key in seen:
            mapping.append({'评论ODS主键':c['id'],'状态':'重复平台评论ID，未重复处理','原文':c.get('评论内容')});continue
        seen.add(key);linked[p['id']].append(c)
    quotas={b.T1:{'微信公众号':125,'小红书':125,'微信视频号':125,'网页':125},
            b.T2:{'小红书':250,'微信公众号':192,'网页':58,'微信视频号':0}}
    rng=random.Random(seed);docs=[];manifest=[];coverage=[];selected=[]
    def group(p):
        n=len(b.choose_source(p)[1]);length='短' if n<1200 else '中' if n<4200 else '长'
        return (length,) if p['项目']==b.T1 else (tuple(b.project_hints(p,business['projects'])),length,
            '1' if len(linked[p['id']])==1 else '2~5' if len(linked[p['id']])<=5 else '6+')
    for topic,channels in quotas.items():
        for channel,n in channels.items():
            raw=[p for p in posts if p.get('项目')==topic and p.get('平台')==channel]
            eligible=[p for p in raw if b.choose_source(p)[1]]
            priorities=[p for p in eligible if linked[p['id']]] if topic==b.T2 else []
            with_comments=b.stratified_pick(priorities,min(n,len(priorities)),rng,group) if priorities else []
            ids={p['id'] for p in with_comments}
            picked=with_comments+b.stratified_pick([p for p in eligible if p['id'] not in ids],n-len(ids),rng,group)
            selected.extend(picked)
            coverage.append({'专题':topic,'平台':channel,'原始文章数':len(raw),'可用主体数':len(eligible),
                '符合抽样条件数':len(eligible),'渠道覆盖抽样数':n,'实际文章测试数':n,
                '选中有评论文章数':len(with_comments),'实际评论测试数':sum(len(linked[p['id']]) for p in picked) if topic==b.T2 else 0,
                '说明':'无可用主体，单独报告缺口' if not eligible else '带评论优先，网页全取后余量分配至公众号' if topic==b.T2 else '四平台均衡，长度分层'})
    for p in selected:
        field,text=b.choose_source(p);docs.append(b.make_document(p,'文章',p,field,text))
        manifest.append({'专题':p['项目'],'平台':p['平台'],'源文章ODS主键':p['id'],'抽样用途':'500篇主体；优先有评论' if p['项目']==b.T2 else '500篇主体',
            '主体字段':field,'字符数':len(text),'关联评论数':len(linked[p['id']]) if p['项目']==b.T2 else 0,'项目候选线索':b.project_hints(p,business['projects'])})
    for p in selected:
        if p['项目']==b.T2:
            docs += [b.make_document(c,'评论',p,'评论内容',c.get('评论内容') or '') for c in sorted(linked[p['id']],key=lambda c:str(c['id']))]
    assert Counter(d['topic'] for d in docs if d['kind']=='文章')=={b.T1:500,b.T2:500}
    assert any(d['kind']=='评论' and b.useful(d['text']) for d in docs),'No real comment sources'
    assert len({d['record_id'] for d in docs})==len(docs)
    return {'documents':docs,'sampling':{'seed':seed,'samples':manifest,'coverage':coverage,'comment_mapping_issues':mapping,
        'requested_articles_per_topic':500,'comments_extra_to_articles':True}}

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output-dir',type=Path,required=True);a=ap.parse_args()
    business=b.load_business();sample=prepare(b.read_csv(Path('C:/Users/YS-Insight/Desktop/ods_social_media_post.csv')),
        b.read_csv(Path('C:/Users/YS-Insight/Desktop/ods_social_media_comment.csv')),business)
    b.save_json(a.output_dir/'sample.json',sample);b.save_json(a.output_dir/'gym_policy.json',{'version':VERSION,'instruction':INSTRUCTION})
    print(b.dumps({'articles':Counter(d['topic'] for d in sample['documents'] if d['kind']=='文章'),
        'comments':sum(d['kind']=='评论' for d in sample['documents']),'empty_comments':sum(d['kind']=='评论' and not b.useful(d['text']) for d in sample['documents']),
        'coverage':sample['sampling']['coverage']}))
