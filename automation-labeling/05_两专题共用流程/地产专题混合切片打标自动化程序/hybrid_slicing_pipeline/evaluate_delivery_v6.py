"""Read-only baseline comparison + explicit evidence anchor tests.

The anchors cover known cases, not a population accuracy/recall estimate.
Offline replay tests program corrections only, never model omission recovery.
"""
import argparse
import json
from pathlib import Path
import delivery_v6 as v

ANCHORS={
    'T2-75359':{'positive':['VOC-0165','VOC-0164','VOC-0416'],'negative':[]},
    'T2-8000912876517502735':{'positive':['VOC-0384','VOC-0380','VOC-0379'],'negative':[]},
    'T2-8000912876517503087':{'positive':['VOC-0165'],'negative':['VOC-0032']},
    'T1-2651643050694719236':{'positive':['VOC-0203'],'negative':[]},
    'T2-C-7963753211120747179':{'positive':[],'negative':['VOC-0032','VOC-0019']},
    'T2-C-7963753211120747182':{'positive':[],'negative':['VOC-0028','VOC-0029']},
}


def compare(before,after):
    def indexed(data):
        return {r['document']['record_id']:{t['标签路径ID'] for u in r['rows'] for t in u['标签明细']} for r in data['results']}
    old,new=indexed(before),indexed(after)
    rows=[]
    for rid,anchors in ANCHORS.items():
        if rid not in new:continue
        for polarity,ids in anchors.items():
            for tid in ids:
                rows.append({'record_id':rid,'标签路径ID':tid,'锚点性质':polarity,
                    '旧版是否标出':tid in old.get(rid,set()),'新版是否标出':tid in new[rid],
                    '锚点通过':(tid in new[rid])==(polarity=='positive')})
    return rows


def main():
    p=argparse.ArgumentParser();p.add_argument('--baseline',type=Path,default=Path(__file__).parent/'test_results_v51_20261009_api/delivery_results.json')
    p.add_argument('--result',type=Path);p.add_argument('--offline-output',type=Path)
    a=p.parse_args();before=json.loads(a.baseline.read_text(encoding='utf-8'))
    if a.offline_output:
        taxonomy=v.base.load_taxonomy(v.legacy.TAXONOMY);business=v.base.load_business();results=[]
        for previous in before['results']:
            doc=previous['document'];calls=previous.get('calls',[])
            if not calls:continue
            saved=json.loads((a.baseline.parent/'calls'/(calls[0]['request_key']+'.json')).read_text(encoding='utf-8'))
            raw=saved['response'];payload=v.legacy.request_payload(doc,taxonomy,business)
            payload['label_catalog']=v.catalogue(taxonomy,doc['topic'])
            result=v.assemble(doc,taxonomy,business,raw,saved['metrics'],payload,
                ['离线重放仅修复程序回填/证据规则；未独立调用模型，不证明首轮遗漏已补齐'],False)
            result['calls']=[];results.append(result)
        after={'summary':{'mode':'offline_replay','note':'未新调用API；没有独立覆盖审核；全部待人工审核'},'results':results}
        rows=compare(before,after);after['anchor_comparison']=rows
        a.offline_output.mkdir(parents=True,exist_ok=True)
        v.base.save_json(a.offline_output/'offline_replay.json',after)
        v.base.write_csv(a.offline_output/'已知问题锚点对比.csv',rows,list(rows[0]) if rows else ['说明'])
    else:
        if not a.result:p.error('--result or --offline-output required')
        after=json.loads(a.result.read_text(encoding='utf-8'));rows=compare(before,after)
        after['tables']['已知问题锚点对比']=rows;after['schemas']['已知问题锚点对比']=list(rows[0]) if rows else ['说明']
        v.base.save_json(a.result,after)
        v.base.write_csv(a.result.parent/'已知问题锚点对比.csv',rows,after['schemas']['已知问题锚点对比'])
    print(v.base.dumps({'anchor_checks':len(rows),'passed':sum(r['锚点通过'] for r in rows),'details':rows}),flush=True)


if __name__=='__main__':main()
