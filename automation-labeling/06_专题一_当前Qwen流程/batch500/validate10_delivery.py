import argparse,importlib.util,json,sys
from pathlib import Path
sys.dont_write_bytecode=True;sys.stdout.reconfigure(encoding='utf8')
ROOT=Path(__file__).parent
PROJECT=Path(__file__).resolve().parents[1]/'semantic-r49'
spec=importlib.util.spec_from_file_location('validate',PROJECT/'validate_delivery.py')
v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)
p=argparse.ArgumentParser();p.add_argument('--count',type=int,choices=[10,500],default=10);args=p.parse_args();count=args.count
file='E:/Codex/outputs/20261022_专题一10篇Qwen效果确认/专题一_Qwen试标10篇_标准10工作表.xlsx' if count==10 else 'E:/Codex/outputs/20261022_专题一500篇Qwen正式交付/专题一_Qwen500篇_标准10工作表.xlsx'
v.validate(str(count),'r49',file_override=file,run_dir=ROOT/f'delivery{count}',source_path=ROOT/f'results_{count}.json')
