"""Read-only deterministic replay up to the boundary request; never call API."""
import argparse
import json
from pathlib import Path
import delivery_v11 as pipeline


class Captured(Exception):pass
class MissingCache(Exception):pass


class CacheOnlyRunner:
    def __init__(self,folder):self.folder=folder;self.payload=None;self.response=None
    def call(self,system,payload,doc,phase):
        base=pipeline.p.base
        limit={'独立专题范围核验':1024,'逐候选决定缺漏裁决':4096,
               '证据核验协议精简修复':8192}.get(phase,base.MAX_OUTPUT_TOKENS)
        key=base.digest({'version':base.VERSION,'base':'http://127.0.0.1:3000',
            'model':'qwen3.7-flash','max_output_tokens':limit,'system':system,'payload':payload})
        path=self.folder/'calls'/(key+'.json')
        if phase=='最终逐原文键边界语义合并-v11.26':
            self.payload=payload
            if path.exists():self.response=json.loads(path.read_text(encoding='utf-8'))['response']
            raise Captured()
        if not path.exists():raise MissingCache(phase+':'+key)
        cache=json.loads(path.read_text(encoding='utf-8'))
        return cache['response'],dict(cache['metrics'],cache_hit=True)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--sample',type=Path,required=True)
    parser.add_argument('--folder',type=Path,required=True);parser.add_argument('--record-id',required=True)
    args=parser.parse_args();sample=json.loads(args.sample.read_text(encoding='utf-8'))
    doc=next(d for d in sample['documents'] if d['record_id']==args.record_id)
    runner=CacheOnlyRunner(args.folder)
    try:
        pipeline.process_document(doc,pipeline.p.base.load_taxonomy(pipeline.p.v.legacy.TAXONOMY),
                                  pipeline.p.base.load_business(),runner)
    except Captured:
        checks={e['edge_key']:e for e in (runner.response or {}).get('edges',[])}
        for entry in runner.payload['edge_catalog']:
            print(json.dumps(dict(entry,model_decision=checks.get(entry['edge_key'])),ensure_ascii=False))
    except MissingCache as exc:print('Read-only replay stopped at missing cache: '+str(exc))


if __name__=='__main__':main()
