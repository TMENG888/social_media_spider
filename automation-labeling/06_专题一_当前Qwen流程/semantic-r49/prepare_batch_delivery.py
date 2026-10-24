"""Use the same standard-10-sheet adapter for the verified 300-source batch."""
import sys
from pathlib import Path
import prepare_regression_delivery as delivery
import validate_delivery as validation
R=Path(__file__).parent
version=sys.argv[1];run=R/'batch300'/version
file=Path('E:/Codex/outputs/20261021_专题一300篇Qwen验证交付')/'专题一_Qwen切片打标_300篇_标准10工作表.xlsx'
if len(sys.argv)>2 and sys.argv[2]=='validate':
    validation.validate('300',version,file_override=file,run_dir=run,source_path=run/'results_300.json')
else:
    delivery.prepare('300',version,source_path=run/'results_300.json',input_path=R/'batch300/documents.json',dest_dir=run)
