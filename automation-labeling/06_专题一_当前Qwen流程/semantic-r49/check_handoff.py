import pathlib,json,hashlib,openpyxl,sys
sys.stdout.reconfigure(encoding='utf8')
r=pathlib.Path(__file__).parent;m=json.loads((r/'manifest.json').read_text(encoding='utf8'))
out=pathlib.Path('E:/Codex/outputs/20261021_专题一参考集ABC');result=[]
prohibited={'项目','验收状态','互动深度指数','涉及文章数','参与文章数','命中切片数','组内全部切片数','有热度文章数','缺热度文章数','字典ID'}
for name,digest in m['references'].items():
 p=out/name
 assert hashlib.sha256(p.read_bytes()).hexdigest()==digest
 wb=openpyxl.load_workbook(p,read_only=True,data_only=False)
 assert len(wb.sheetnames)==10
 for ws in wb:
  hs=list(next(ws.iter_rows(min_row=5,max_row=5,values_only=True)))
  assert not prohibited.intersection(hs)
  assert ws.sheet_state=='visible'
 result.append({'file':name,'size':p.stat().st_size,'sheets':len(wb.sheetnames)})
 wb.close()
print(json.dumps(result,ensure_ascii=False))
calls=[json.loads(p.read_text(encoding='utf8'))['metrics'] for p in (r/'api_cache/calls').glob('*.json')]
audit={'calls_cached':len(calls),'status_counts':{s:sum(c['status']==s for c in calls) for s in set(c['status'] for c in calls)},'prompt_tokens':sum(c.get('prompt_tokens') or 0 for c in calls),'completion_tokens':sum(c.get('completion_tokens') or 0 for c in calls),'price_unavailable_calls':sum(c.get('estimated_yuan') is None for c in calls)}
(r/'api_usage_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(audit,ensure_ascii=False))
