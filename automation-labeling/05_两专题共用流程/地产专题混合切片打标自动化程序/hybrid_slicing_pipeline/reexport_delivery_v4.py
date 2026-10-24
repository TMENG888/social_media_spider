"""Rebuild CSV/JSON from existing results, WITHOUT any API or DB writes."""
import argparse
import json
from pathlib import Path
from types import SimpleNamespace
import delivery_v4 as v

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('output_dir',type=Path);args=p.parse_args()
    old=json.loads((args.output_dir/'delivery_results.json').read_text(encoding='utf-8'))
    data=v.export(args.output_dir,old['results'],old['sampling'],[],old['business'],
                  SimpleNamespace(calls=old['calls']),old['summary']['mode'],old['summary']['smoke_passed'])
    # No taxonomy reload/relabel is performed: retain the actual test signature.
    data['taxonomy_signature']=old['taxonomy_signature']
    v.save_json(args.output_dir/'delivery_results.json',data)
    print(json.dumps(data['summary'],ensure_ascii=False,indent=2))
