"""Offline audit. Never imported by the Qwen runner; C requires a freeze."""
import sys,json,re
from pathlib import Path
from collections import Counter,defaultdict
import evaluate
R=Path(__file__).parent
sys.stdout.reconfigure(encoding='utf8')
def audit(batch,path):
 if batch=='C' and not (R/'frozen_version.json').exists():raise RuntimeError('C sealed')
 results=evaluate.read(path);tax={t['tag_id']:t for t in evaluate.read(R/'inputs/taxonomy.json')}
 ref=evaluate.refs(batch);rg=defaultdict(list)
 for u in ref:rg[str(u['源表id'])].append(u)
 errors=[];meta=[];summaries=[];decisions=[];ledger=[]
 for r in results:
  d=r['document'];sid=d['source_id'];parts=r['semantic_partition'];pos=0
  for u in parts:
   if u['start']!=pos or u['end']<=u['start'] or d['text'][u['start']:u['end']]!=u['text']:errors.append([sid,'partition',u['index']])
   pos=u['end']
   ids=[l['tag_id'] for l in u['labels']]
   if len(ids)!=len(set(ids)):errors.append([sid,'duplicate_tag',u['index']])
   for l in u['labels']:
    if l['tag_id'] not in tax or not l.get('quote') or l['quote'] not in u['text']:errors.append([sid,'label_proof',u['index'],l['tag_id']])
    ledger.append({'source_id':sid,'index':u['index'],'deliver':u['deliver'],'tag':l['tag_id'],'path':'/'.join(tax[l['tag_id']].get(k) or '' for k in ['l2','l3','l4','l5']),'quote':l['quote'],'reason':l['reason']})
   if u['deliver']:
    # Flags for human review only; unit conversion/ASR corrections may be valid.
    raw_numbers=set(re.findall(r'\d+(?:\.\d+)?',u['text']))
    new_numbers=set(re.findall(r'\d+(?:\.\d+)?',u.get('practice','')))-raw_numbers
    if new_numbers:summaries.append({'source_id':sid,'index':u['index'],'new_numeric_tokens':sorted(new_numbers),'raw':u['text'],'practice':u['practice']})
  if pos!=len(d['text']):errors.append([sid,'partition_tail'])
  checks=[c for g in r['label_audit']['table_audit'] for c in g['result']['checks']]
  counts=Counter(c['tag_id'] for c in checks)
  if set(counts)!=set(tax) or any(v!=1 for v in counts.values()):errors.append([sid,'taxonomy_coverage'])
  decisions.append({'source_id':sid,'taxonomy_decisions':len(checks),'candidate_verdicts':len(r['label_audit']['verdicts']),'delivered_units':len(r['rows']),'all_units':len(parts)})
  fields={}
  for f in ['品牌组','经营主体','城市','发布者角色']:
   g=sorted({u[f] for u in rg[sid] if u[f]});p=sorted({u.get(f) for u in r['rows'] if u.get(f)})
   fields[f]={'reference':g,'model':p,'match':g==p,'note':'差异须按原文核查，不将参考空值视为禁止补全'}
  meta.append({'source_id':sid,'fields':fields})
 out={'batch':batch,'source_count':len(results),'structural_errors':errors,'metadata':meta,'summary_numeric_review':summaries,'coverage':decisions,'label_evidence_ledger':ledger,'note':'标签证据、摘要忠实性、空间对象及身份关联仍需人工语义复核；检查通过不自动等于生产验收。'}
 dest=Path(path).with_name('audit_'+batch+'.json');dest.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf8')
 print(json.dumps({k:v for k,v in out.items() if k not in ['label_evidence_ledger','metadata']},ensure_ascii=False))
 print('METADATA',json.dumps(meta,ensure_ascii=False))
if __name__=='__main__':audit(sys.argv[1],sys.argv[2])
