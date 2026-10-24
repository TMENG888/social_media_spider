import json,sys,io,contextlib
from pathlib import Path
import evaluate,audit_result
R=Path(__file__).parent
version=sys.argv[1]
for batch in sys.argv[2:]:
    file=R/f'run_{version}'/f'{batch}_results.json'
    with contextlib.redirect_stdout(io.StringIO()):
        evaluate.evaluate(batch,file)
        audit_result.audit(batch,file)
    e=json.loads(file.with_name(f'evaluation_{batch}.json').read_text(encoding='utf8'))
    a=json.loads(file.with_name(f'audit_{batch}.json').read_text(encoding='utf8'))
    print(json.dumps({'batch':batch,'sources':e['model_sources'],'source_tag':e['source_tag'],'span_tag':e['span_tag'],'structural_errors':e['structural_errors']+a['structural_errors'],'duplicates':e['duplicate_slices'],'empty_practice':e['empty_practice'],'summary_numeric_anomalies':len(a['summary_numeric_review'])},ensure_ascii=False))
