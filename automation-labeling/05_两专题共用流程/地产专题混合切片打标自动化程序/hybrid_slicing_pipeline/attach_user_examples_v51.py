"""Attach saved, separately billed real-API regression examples; no new API."""
import json
from pathlib import Path
import delivery_v5 as v
from finalize_delivery_v51 import Recorded

if __name__=='__main__':
    root=v.base.ROOT/'test_results_v51_20261009_api'
    example_root=v.base.ROOT/'test_user_examples_v51_20261009_api'
    main=json.loads((root/'delivery_results.json').read_text(encoding='utf-8'))
    old=json.loads((example_root/'examples_results.json').read_text(encoding='utf-8'))
    records={}
    for f in (example_root/'calls').glob('*.json'):
        saved=json.loads(f.read_text(encoding='utf-8'));records[saved['metrics']['record_id']]=saved
    taxonomy=v.base.load_taxonomy(v.TAXONOMY);runner=Recorded(records)
    results=[v.process_document(r['document'],taxonomy,main['business'],runner) for r in old['results']]
    v.base.save_json(example_root/'examples_results_final.json',{'results':results,'calls':old['calls']})
    rows=[]
    for r in results:
        d=r['document']
        common={'record_id':d['record_id'],'来源类型':d['kind'],'源表id':d['source_id'],
                '父文章ODS主键':d['parent']['id'],'父文章平台文章id':d['parent'].get('文章id'),
                '评论源表文章id':d['row'].get('文章id') if d['kind']=='评论' else None}
        for u in r['rows']:rows.append({**common,**u})
        if not r['rows']:rows.append({**common,'原始摘录':d['text'],'处理结果':'排除/异常','审核说明':'；'.join(a['原因'] for a in r['audit'])})
    main['tables']['指定样例回归']=rows
    main['summary']['指定样例API请求数']=len(old['calls'])
    main['summary']['指定样例已知费用元']=sum(c['estimated_yuan'] for c in old['calls'] if c['estimated_yuan'] is not None)
    main['summary']['指定样例未知费用请求数']=sum(c['estimated_yuan'] is None for c in old['calls'])
    main['summary']['指定样例说明']='指定样例独立于80篇渠道抽样，不计入主批次单元数；单独记录调用费用。'
    v.base.save_json(root/'delivery_results.json',main)
    v.base.write_csv(root/'指定样例回归.csv',rows,list(dict.fromkeys(k for r in rows for k in r)))
    print(v.base.dumps(rows))
