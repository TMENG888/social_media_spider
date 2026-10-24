"""Read-only saved-XLSX verification, independent of the authoring engine."""
import argparse,json
from pathlib import Path
from collections import Counter
import openpyxl
from delivery_v4 import save_json,load_taxonomy,label_json,T1,T2

def verify(output,taxonomy,workbook_dir=None):
 workbook_dir=workbook_dir or output
 tags={t['tag_id']:label_json(t) for t in load_taxonomy(taxonomy)};books=[]
 for name,topic in [('产品信息单元',T1),('观点信息单元',T2)]:
  payload=json.loads((output/(name+'_workbook_payload.json')).read_text(encoding='utf-8'))
  workbook_path=workbook_dir/payload['filename']
  assert workbook_path.is_file() and workbook_path.stat().st_size>0,'Missing or empty saved workbook: '+str(workbook_path)
  wb=openpyxl.load_workbook(workbook_path,read_only=True,data_only=True)
  source=wb['源记录与文章关联'];headers=next(source.iter_rows(values_only=True));sources=[dict(zip(headers,row)) for row in source.iter_rows(min_row=2,values_only=True)]
  count=Counter(r['来源类型'] for r in sources);assert count['文章']==500
  assert count['评论']==(956 if topic==T2 else 0)
  main=wb[name];headers=next(main.iter_rows(values_only=True));rows=[dict(zip(headers,row)) for row in main.iter_rows(min_row=2,values_only=True)]
  assert len(rows)==len(payload['tables'][name])
  if topic==T2:assert any(r.get('来源类型')=='评论' for r in rows),'No verified comment unit; do not present article-only output as a complete delivery'
  by_source={r['record_id']:r for r in sources};ids=set()
  for r in rows:
   assert r['unit_id'] not in ids;ids.add(r['unit_id'])
   parsed=json.loads(r['标签明细']);assert parsed and all(t==tags[t['标签路径ID']] for t in parsed)
   assert r['打标说明'] and r.get('具体产品做法',r.get('观点摘要'))
   if r.get('来源类型')=='评论':
    s=by_source[r['record_id']];assert r['原始摘录']==s['原始主体'] and r['映射文章id']==s['评论平台文章id']
  dictionary=wb['专题一标签体系' if topic==T1 else '专题二标签体系'];head=next(dictionary.iter_rows(min_row=5,max_row=5,values_only=True))
  gym=next(dict(zip(head,row)) for row in dictionary.iter_rows(min_row=6,values_only=True) if row[0]=='VOC-0377')
  assert '无需具体器械' in gym['打标说明']
  books.append({'file':payload['filename'],'path':str(workbook_path.resolve()),'bytes':workbook_path.stat().st_size,'articles':count['文章'],'comments':count['评论'],'main_units':len(rows),'passed':True})
  wb.close()
 save_json(output/'saved_workbooks_verification.json',{'passed':True,'workbook_dir':str(workbook_dir.resolve()),'workbooks':books});print(json.dumps(books,ensure_ascii=False))

if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--output-dir',type=Path,required=True);ap.add_argument('--taxonomy',type=Path,required=True);ap.add_argument('--workbook-dir',type=Path);a=ap.parse_args();verify(a.output_dir,a.taxonomy,a.workbook_dir)
