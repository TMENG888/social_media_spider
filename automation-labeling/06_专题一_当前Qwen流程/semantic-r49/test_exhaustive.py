import json,sys,copy,argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
sys.dont_write_bytecode=True;sys.stdout.reconfigure(encoding='utf8');R=Path(__file__).parent
sys.path.insert(0,str(R/'production_snapshot'))
import delivery_v4 as api
import exhaustive_labels as ex
def read(p):return json.loads(Path(p).read_text(encoding='utf8'))
def save(p,x):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf8');tmp.replace(p)
def main():
 p=argparse.ArgumentParser();p.add_argument('--indices',default='0,3');p.add_argument('--batch-size',type=int,default=24);p.add_argument('--version',default='r9_probe');args=p.parse_args()
 previous=read(R/'r8_audit/results.json');chosen=[previous[int(i)] for i in args.indices.split(',')]
 tax=read(R/'inputs/taxonomy.json');tm={t['tag_id']:t for t in tax};runner=api.ApiRunner(R/'api_cache',concurrency=6);out=R/args.version
 allresults=[];errors=[]
 for result in chosen:
  d=result['document'];units=result['semantic_partition'];merged={u['index']:[] for u in units};audit=[]
  with ThreadPoolExecutor(max_workers=6) as pool:
   fs={pool.submit(ex.classify_group,d,units,tax[a:a+args.batch_size],runner):a for a in range(0,len(tax),args.batch_size)}
   for f in as_completed(fs):
    a=fs[f]
    try:
     labels,raw=f.result();audit.append({'start':a,'response':raw})
     for i,labels_i in labels.items():merged[i].extend(labels_i)
    except Exception as e:errors.append({'source':d['source_id'],'start':a,'error':str(e)})
  save(out/(d['record_id']+'_draft.json'),{'labels':merged,'table_audit':audit,'errors':errors})
  verified={u['index']:[] for u in units};checks=[]
  with ThreadPoolExecutor(max_workers=6) as pool:
   fs={pool.submit(ex.verify_pair,d,u,label,tm[label['tag_id']],runner):(u['index'],label['tag_id']) for u in units for label in merged[u['index']]}
   for f in as_completed(fs):
    i,tid=fs[f]
    try:
     proof,answer=f.result();checks.append({'index':i,'tag_id':tid,'verdict':answer})
     if proof:verified[i].append(proof)
    except Exception as e:errors.append({'source':d['source_id'],'unit':i,'tag_id':tid,'error':str(e)})
  # The experiment isolates tagging. Semantic boundaries/metadata stay frozen;
  # rows are carried from r8 plus valid tagged previously unshown segments.
  rows=[];traces=[]
  for u in units:
   labels=verified[u['index']];u['labels']=labels
   if not u['deliver'] and not labels:continue
   old=next((copy.deepcopy(r) for r in result['rows'] if r['起点']==u['start'] and r['终点']==u['end']),{})
   tags=[]
   for x in labels:
    t=tm[x['tag_id']];tags.append({'标签路径ID':t['tag_id'],'标签编号':t['source_number'],**{name:t[k] or None for name,k in [('一级标签','l1'),('二级标签','l2'),('三级标签','l3'),('四级标签','l4'),('五级标签','l5'),('标签强调方向','emphasis')]}})
   old.update({'unit_id':d['record_id']+f'-E{u["index"]:03}','原文摘录':u['text'],'起点':u['start'],'终点':u['end'],'标签明细':tags,'具体产品做法':u.get('practice') or '', '品牌组':u.get('brand'),'经营主体':old.get('经营主体','')})
   rows.append(old);traces.append({'起点':u['start'],'终点':u['end']})
  result['rows']=rows;result['traces']=traces;result['checks']=checks;result['labels_before_review']=merged;allresults.append(result)
  save(out/'results.json',allresults);save(out/'status.json',{'sources':len(allresults),'errors':errors});print(json.dumps({'source':d['source_id'],'initial_pairs':sum(map(len,merged.values())),'verified_pairs':sum(map(len,verified.values())),'errors':errors},ensure_ascii=False),flush=True)
 save(out/'calls.json',runner.calls)
 if errors:raise RuntimeError('Some decisions failed, cannot claim a passed experiment')
if __name__=='__main__':main()
