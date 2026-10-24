"""Preserve production sources and only previously referenced API caches."""
import json,shutil
import argparse
from pathlib import Path
import delivery_v11 as pipeline

root=Path(__file__).parent
parser=argparse.ArgumentParser()
parser.add_argument('--previous',default='test_results_v11_51_random_20261009_api')
parser.add_argument('--output',default='test_results_v11_52_random_20261009_api')
parser.add_argument('--previous-result',default='delivery_results.json')
parser.add_argument('--copy-all-calls',action='store_true')
parser.add_argument('--pipeline-module',default='delivery_v11',choices=['delivery_v11','delivery_v59','delivery_v60','delivery_v61','delivery_v62','delivery_v63','delivery_v64','delivery_v65','delivery_v66','delivery_v67','delivery_v68','delivery_v69','delivery_v70','delivery_v71','delivery_v72','delivery_v74'])
parser._option_string_actions['--pipeline-module'].choices.append('delivery_v75')
parser._option_string_actions['--pipeline-module'].choices.append('delivery_v76')
args=parser.parse_args()
if args.pipeline_module=='delivery_v76':
    import delivery_v76
    delivery_v76.activate()
if args.pipeline_module=='delivery_v75':
    import delivery_v75
    delivery_v75.activate()
if args.pipeline_module=='delivery_v74':
    import delivery_v74
    delivery_v74.activate()
if args.pipeline_module=='delivery_v72':
    import delivery_v72
    delivery_v72.activate()
if args.pipeline_module=='delivery_v71':
    import delivery_v71
    delivery_v71.activate()
if args.pipeline_module=='delivery_v70':
    import delivery_v70
    delivery_v70.activate()
if args.pipeline_module=='delivery_v69':
    import delivery_v69
    delivery_v69.activate()
if args.pipeline_module=='delivery_v68':
    import delivery_v68
    delivery_v68.activate()
if args.pipeline_module=='delivery_v67':
    import delivery_v67
    delivery_v67.activate()
if args.pipeline_module=='delivery_v59':
    import delivery_v59
    delivery_v59.activate()
elif args.pipeline_module=='delivery_v60':
    import delivery_v60
    delivery_v60.activate()
elif args.pipeline_module=='delivery_v61':
    import delivery_v61
    delivery_v61.activate()
elif args.pipeline_module=='delivery_v62':
    import delivery_v62
    delivery_v62.activate()
elif args.pipeline_module=='delivery_v63':
    import delivery_v63
    delivery_v63.activate()
elif args.pipeline_module=='delivery_v64':
    import delivery_v64
    delivery_v64.activate()
elif args.pipeline_module=='delivery_v65':
    import delivery_v65
    delivery_v65.activate()
elif args.pipeline_module=='delivery_v66':
    import delivery_v66
    delivery_v66.activate()
old=root/args.previous
new=root/args.output
if (new/'frozen_production_snapshot').exists():raise SystemExit('Snapshot already exists; do not replace a running version')
snapshot=new/'frozen_production_snapshot';snapshot.mkdir(parents=True)
for name in pipeline.IMPLEMENTATION_FILES:shutil.copy2(root/name,snapshot/name)
previous_file=old/args.previous_result
if previous_file.exists():
    data=json.loads(previous_file.read_text(encoding='utf-8'))
elif args.copy_all_calls:
    # A stopped, checkpointed batch may not have its final aggregate yet.
    # Copy exact request caches only; never claim unfinished documents complete.
    data={'results':[]}
else:
    raise SystemExit('Previous aggregate missing; --copy-all-calls is required for an interrupted batch')
keys={c['request_key'] for result in data['results'] for c in result['calls']}
if args.copy_all_calls:keys.update(f.stem for f in (old/'calls').glob('*.json'))
(new/'calls').mkdir()
copied=0
for key in keys:
    source=old/'calls'/(key+'.json')
    if source.exists():shutil.copy2(source,new/'calls'/source.name);copied+=1
(new/'preparation.json').write_text(json.dumps({'version':pipeline.VERSION,'copied_referenced_cache_files':copied,
    'source_result':str(old/args.previous_result),'copy_all_exact_request_caches':args.copy_all_calls,
    'snapshot_files':pipeline.IMPLEMENTATION_FILES},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'version':pipeline.VERSION,'copied':copied},ensure_ascii=False))
