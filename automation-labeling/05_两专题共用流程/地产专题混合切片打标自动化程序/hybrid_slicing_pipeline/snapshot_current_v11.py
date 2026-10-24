"""Read only exact current-signature checkpoints; ignore old-version files."""
import argparse,json
from pathlib import Path
import delivery_v11 as v

def current_results(sample,folder):
    taxonomy=v.p.base.load_taxonomy(v.p.v.legacy.TAXONOMY);business=v.p.base.load_business()
    implementation=v.p.base.digest({name:Path(v.__file__).with_name(name).read_text(encoding='utf-8') for name in v.IMPLEMENTATION_FILES})
    signature=v.p.base.digest({'version':v.VERSION,'implementation':implementation,'taxonomy':taxonomy,'business':business,
        'api_base_url':'http://127.0.0.1:3000','model':'qwen3.7-flash'})
    results=[]
    for doc in sample['documents']:
        path=folder/'documents'/(v.p.base.digest({'signature':signature,'document':doc})+'.json')
        if path.exists():results.append(json.loads(path.read_text(encoding='utf-8')))
    return results

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--sample',type=Path,required=True)
    parser.add_argument('--folder',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--pipeline-module',default='delivery_v11',choices=['delivery_v11','delivery_v59','delivery_v60','delivery_v61','delivery_v62','delivery_v63','delivery_v64','delivery_v65','delivery_v66','delivery_v67','delivery_v68','delivery_v69','delivery_v70','delivery_v71','delivery_v72','delivery_v74'])
    parser._option_string_actions['--pipeline-module'].choices.append('delivery_v75')
    args=parser.parse_args();sample=json.loads(args.sample.read_text(encoding='utf-8'))
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
    results=current_results(sample,args.folder)
    v.p.base.save_json(args.output,{'results':results,'planned_sources':len(sample['documents']),'version':v.VERSION})
    print(v.p.base.dumps({'current_sources':len(results),'planned_sources':len(sample['documents'])}))
if __name__=='__main__':main()
