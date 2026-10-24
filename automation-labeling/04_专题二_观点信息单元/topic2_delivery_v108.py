"""Standard final export; no model calls and no rewriting source checkpoints."""
import json,subprocess,uuid,os,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parent
SCHEMA=ROOT/'topic2_delivery_schema_v108.json'
NODE=Path(os.environ.get('LABEL_NODE') or shutil.which('node') or 'node')
DEPS=Path(os.environ.get('LABEL_NODE_MODULES',str(NODE.parent.parent/'node_modules')))
def export_workbook(payload,output_path,*,work_dir=None,node=NODE,dependency_root=DEPS,preview_dir=None):
    from topic2_heat_v110 import refresh_payload_heat
    payload=refresh_payload_heat(payload)
    output=Path(output_path).resolve()
    if output.suffix.lower()!='.xlsx':raise ValueError('Final delivery requires .xlsx')
    if work_dir is None:
        if output.drive.upper()!='E:':raise ValueError('Set an explicit E-drive work_dir for intermediate export files')
        work_dir=output.parent/'export_state'
    work=Path(work_dir).resolve()
    if work.drive.upper()!='E:':raise ValueError('Export intermediate files must stay on E:')
    work.mkdir(parents=True,exist_ok=True)
    input_file=work/(output.stem+'.'+uuid.uuid4().hex+'.payload.json')
    # Computation payload and audits remain internal. Final v111 delivery has
    # nine sheets, excluding five audit tabs and four legacy detail fields.
    input_file.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
    command=[str(node),str(ROOT/'export_topic2_v108.mjs'),str(input_file),str(output),str(dependency_root)]
    if preview_dir:command.append(str(preview_dir))
    result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8')
    receipt=Path(str(output)+'.schema.json')
    if not output.exists() or not receipt.exists():
        raise RuntimeError('Final export did not complete: '+result.stderr[-3000:]+result.stdout[-1500:])
    # Some bundled renderer versions return 1 at shutdown after successful
    # export. Accept only a fresh, schema-verified receipt for this invocation.
    report=json.loads(receipt.read_text(encoding='utf-8'))
    if Path(report.get('input_file','')).resolve()!=input_file:
        raise RuntimeError('No fresh export receipt for the current invocation')
    expected=json.loads(SCHEMA.read_text(encoding='utf-8'))
    if [(s['name'],s['headers'],s['side_headers']) for s in report['sheets']]!=[(s['name'],s['headers'],s['side_headers']) for s in expected['sheets']]:
        raise RuntimeError('Exported worksheet schema differs from authorized standard')
    detail=next(s for s in report['sheets'] if s['name']=='打标明细')
    if report.get('detail_grain')!='source-and-original-span-v109' or report.get('duplicate_detail_rows')!=0 or report.get('unique_detail_rows')!=detail['rows']:
        raise RuntimeError('Final detail is not unique per original source slice')
    return {'file':str(output),'schema_version':report['schema_version'],'sheets':len(report['sheets']),'detail_fields':23,'unique_detail_rows':detail['rows'],'process_exit_code':result.returncode}
