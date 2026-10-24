"""Recheck saved Qwen intervals against raw evidence, not Codex answers.

This diagnostic intentionally does not evaluate whole-source precision/recall.
It does not mutate saved outputs, gold labels, production, or the batch gate.
"""
import json,sys,copy
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
R=Path(__file__).parent
sys.dont_write_bytecode=True;sys.stdout.reconfigure(encoding='utf8')
sys.path.insert(0,str(R/'production_snapshot'))
import delivery_v4 as api
import exhaustive_labels as ex

def main():
 version=sys.argv[1]
 tax={t['tag_id']:t for t in json.loads((R/'inputs/taxonomy.json').read_text(encoding='utf8'))}
 runner=api.ApiRunner(R/'api_cache',concurrency=6)
 cases=[('1898812241126862398',4,'VOC-0339'),('1898812241126862398',2,'VOC-0186'),
        ('3661181161938508310',1,'VOC-0178'),('3661181161938508310',2,'VOC-0265'),
        ('3661181161938508310',3,'VOC-0245'),('3661181161938508310',4,'VOC-0285'),
        ('75512',3,'VOC-0235'),('75512',4,'VOC-0238'),
        ('2382843768089334133',9,'VOC-0168'),('2382843768089334133',10,'VOC-0209'),
        ('2382843768089334133',1,'VOC-0167')]
 def work(case):
  sid,index,tid=case
  result=json.loads((R/'batch300/r31/sources'/f'T1-{sid}.json').read_text(encoding='utf8'))['result']
  unit=copy.deepcopy(next(u for u in result['semantic_partition'] if u['index']==index))
  proof,verdict=ex.verify_pair(result['document'],unit,{'tag_id':tid},tax[tid],runner)
  unit['labels']=[proof] if proof else []
  kept,joint=ex.joint_review(result['document'],unit,[tax[tid]],runner)
  return {'source_id':sid,'index':index,'tag_id':tid,'raw':unit['text'],'selected':bool(kept),'verdict':verdict,'joint':joint}
 with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(work,cases))
 out=R/'diagnostics'/version;out.mkdir(parents=True,exist_ok=True)
 (out/'stage_risks.json').write_text(json.dumps({'results':results,'calls':runner.calls},ensure_ascii=False,indent=2),encoding='utf8')
 print(json.dumps([{'source_id':x['source_id'],'index':x['index'],'tag_id':x['tag_id'],'selected':x['selected'],'reason':x['verdict']['reason']} for x in results],ensure_ascii=False))

if __name__=='__main__':main()
