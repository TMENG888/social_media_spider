"""Real API regression for three reported cases, separate from channel sample."""
import getpass
import os
from pathlib import Path
import delivery_v5 as v

if __name__=='__main__':
    root=v.base.ROOT/'test_user_examples_v51_20261009_api';root.mkdir(exist_ok=True)
    posts=v.base.read_csv(Path('C:/Users/YS-Insight/Desktop/ods_social_media_post.csv'))
    comments=v.base.read_csv(Path('C:/Users/YS-Insight/Desktop/ods_social_media_comment.csv'))
    pi={r['id']:r for r in posts};ci={r['id']:r for r in comments}
    index=v.base.PostIndex(posts);business=v.base.load_business();taxonomy=v.base.load_taxonomy(v.TAXONOMY)
    p=pi['8000912876517502830'];field,text=v.base.choose_source(p)
    docs=[v.base.make_document(p,'文章',p,field,text)]
    for cid in ['7963753211120747237','7963753211120747215']:
        c=ci[cid];parent,status=index.map_comment(c)
        if not parent or c['文章id']!=parent['文章id']:raise ValueError(status)
        docs.append(v.base.make_document(c,'评论',parent,'评论内容',c['评论内容']))
    v.base.VERSION=v.VERSION
    runner=v.base.ApiRunner(root,10,key=os.getenv('YS_LLM_API_KEY') or getpass.getpass('API key (hidden, process only): '))
    results=[v.process_document(d,taxonomy,business,runner) for d in docs]
    data={'results':results,'calls':runner.calls}
    v.base.save_json(root/'examples_results.json',data)
    for r in results:
        print(v.base.dumps({'record_id':r['document']['record_id'],'complete':r['complete'],'rows':r['rows'],'audit':r['audit']}),flush=True)
