"""Read-only original CSV reconciliation, independent of saved source traces."""
import argparse
import hashlib
import json
from pathlib import Path
from collections import Counter
import delivery_v4 as base

POST=Path('C:/Users/YS-Insight/Desktop/ods_social_media_post.csv')
COMMENT=Path('C:/Users/YS-Insight/Desktop/ods_social_media_comment.csv')


def associated_comment_ids(comments,index,selected_article_ids):
    """Parent linkage owns coverage; a comment's project value is not a filter."""
    expected=set()
    for row in comments:
        parent,status=index.map_comment(row)
        if parent and parent['id'] in selected_article_ids:expected.add(row['id'])
    return expected


def inspect(data,posts,comments):
    post_by_id={r['id']:r for r in posts};comment_by_id={r['id']:r for r in comments}
    index=base.PostIndex(posts);errors=[];checked=[]
    documents=[r['document'] for r in data['results']]
    article_ids={d['source_id'] for d in documents if d['kind']=='文章'}
    selected_t2={d['source_id'] for d in documents if d['kind']=='文章' and d['topic']==base.T2}
    actual_comment_ids={d['source_id'] for d in documents if d['kind']=='评论'}
    expected_comment_ids=associated_comment_ids(comments,index,selected_t2)
    if expected_comment_ids!=actual_comment_ids:
        errors.append({'requirement':'选中文章全部已有评论，无替换或遗漏',
            'missing':sorted(expected_comment_ids-actual_comment_ids),
            'extra':sorted(actual_comment_ids-expected_comment_ids)})
    for doc in documents:
        row=(post_by_id if doc['kind']=='文章' else comment_by_id).get(doc['source_id'])
        issues=[]
        if not row:issues.append('原CSV主键不存在')
        elif row!=doc['row']:issues.append('保存来源字段与原CSV不一致')
        if row and doc['kind']=='文章':
            field,text=base.choose_source(row)
            if (doc['field'],doc['text'])!=(field,text):issues.append('主体优先级或逐字正文不一致')
            if doc['parent']!=row:issues.append('文章父来源不是自身')
        elif row:
            parent,status=index.map_comment(row)
            if not parent or parent!=doc['parent']:issues.append('原CSV父文章唯一映射不一致：'+status)
            if doc['text']!=(row.get('评论内容') or ''):issues.append('完整评论文本与原CSV不一致')
        checked.append({'record_id':doc['record_id'],'passed':not issues,'issues':issues})
        errors.extend({'record_id':doc['record_id'],'requirement':x} for x in issues)
    channels=Counter((d['topic'],d['row'].get('平台')) for d in documents if d['kind']=='文章')
    return {'checked_sources':len(documents),'checked_articles':len(article_ids),
        'expected_comments':len(expected_comment_ids),'actual_comments':len(actual_comment_ids),
        'channel_counts':[{'专题':t,'平台':p,'文章数':n} for (t,p),n in sorted(channels.items())],
        'checks':checked,'errors':errors,'scope':'全批与当前原CSV逐字段及全文、全量评论关联核对；不证明语义打标准确率'}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('input',type=Path)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    report=inspect(json.loads(args.input.read_text(encoding='utf-8')),base.read_csv(POST),base.read_csv(COMMENT))
    report['csv_sha256']={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in (POST,COMMENT)}
    base.save_json(args.output,report)
    print(base.dumps({k:report[k] for k in ('checked_sources','checked_articles','expected_comments','actual_comments','errors')}))
    raise SystemExit(bool(report['errors']))
