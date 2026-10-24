"""Extra source-owned references, schema checks and changes (read-only inputs)."""
import json
from pathlib import Path
import argparse
from experiment_routes_v78 import IDS
from evaluate_independent_label_anchors_v59 import evaluate

EXTRA=[
 {'record_id':'T2-2188228096999350274','quote':'海晏：标准层3.2米，局部楼栋3.6米','required':['VOC-0195'],'forbidden':[],
  'project_id':'C01','project_name':'建发海晏','basis':'同文建发海晏的住宅层高，不是土地规划条件。'},
 {'record_id':'T2-2188228096999350274','quote':'下沉会所3600㎡，功能更全、空间更气派','required':['VOC-0374'],'forbidden':[],
  'project_id':'C01','project_name':'建发海晏','basis':'连续前文建发海晏园林和会所对象承接。'},
 {'record_id':'T2-8000912876517502948','quote':'西冉地块：容积率1.6，限高25米','required':['VOC-0124','VOC-0127'],'forbidden':[],
  'project_id':None,'project_contains':'西冉','basis':'西冉是字典外地块，不是C05或C07。'},
 {'record_id':'T2-8000912876517502948','quote':'按照政策趋势及地块条件，预计主推120㎡—240㎡户型（约700套）。','required':['VOC-0167'],'forbidden':[],
  'project_id':None,'project_contains':'西冉','basis':'预计户数，保留模态；上下文实际对象西冉。'},
 {'record_id':'T2-8000912876517502948','quote':'西冉板块：距离地铁四季青站步行距离不近，日常出行基本以自驾为主','required':['VOC-0142'],'forbidden':[],
  'project_id':None,'project_contains':'西冉','basis':'地铁通行事实明确，不强求精确距离。'},
 {'record_id':'T2-8000912876517502948','quote':'半壁店板块：步行十余分钟可达6号线田村站，轨道交通优势突出','required':['VOC-0142'],'forbidden':[],
  'project_id':'C05','project_name':'保利熙瑞','basis':'全文明确保利熙瑞(半壁店地块)对应关系。'},
 {'record_id':'T2-C-7963753211120747186','quote':'有个地铁总比没有好呀，我家里两辆车但是家里有四个人','required':['VOC-0005','VOC-0062'],'forbidden':[],
  'basis':'子评者明确家庭人数与交通关注，不能把父评推测套给所有人。'},
 {'record_id':'T2-C-7963753211120747277','quote':'再补一个西冉的大飞机[视频]10s','required':[],'forbidden':['VOC-0157'],
  'project_id':None,'project_contains':'西冉','basis':'没有声音/噪音解析，父文不能补造噪音体验。'},
 {'record_id':'T1-182247585093626012','quote':'干区地漏设置自动补水功能','required':['VOC-0294'],'forbidden':[],
  'basis':'同一卫生间防反味工法样板展示，不是已交付证明。'},
 {'record_id':'T1-75441','quote':'此外，业主反映，开发商原先承诺的电梯品牌是蒂森克虏伯，现在却换成了日立。','required':['VOC-0349'],'forbidden':[],
  'basis':'轿厢品牌变更；保留业主反映口径，不当独立实证。'}]

def evaluate_projects(data):
 records={r['document']['record_id']:r for r in data['results']}; out=[]
 for a in EXTRA:
  if 'project_id' not in a:continue
  result=records[a['record_id']];matched=[r for r in result['rows'] if a['quote'] in r.get('原文摘录',r.get('原始摘录',''))]
  def correct(row):
   ids=row.get('project_id');names=row.get('项目名称')
   if isinstance(ids,list):
    return any(i==a['project_id'] and ((n==a['project_name']) if 'project_name' in a else a['project_contains'] in n)
      for i,n in zip(ids,names or []))
   return ids==a['project_id'] and (names==a['project_name'] if 'project_name' in a else a['project_contains'] in (names or ''))
  out.append(dict(a,passed=bool(matched) and all(correct(r) for r in matched),
   actual=[{'unit_id':r['unit_id'],'id':r.get('project_id'),'name':r.get('项目名称')} for r in matched]))
 return out

def main():
 p=argparse.ArgumentParser();p.add_argument('--baseline',type=Path,required=True);p.add_argument('--root',type=Path,required=True)
 p.add_argument('--d',type=Path)
 a=p.parse_args();read=lambda path:json.loads(path.read_text(encoding='utf-8'))
 full=read(a.baseline);base=dict(full,results=[r for r in full['results'] if r['document']['record_id'] in IDS])
 data={'baseline':base,**{route:read(a.root/route/'delivery_results.json') for route in 'ABC'}}
 if a.d:data['D']=read(a.d)
 ref={'reference_type':'独立对照原文与VOC定义的有限参考锚点，未经人类签核','anchors':EXTRA}
 reports={}
 base_by={r['document']['record_id']:r for r in base['results']}
 for name,d in data.items():
  projects=evaluate_projects(d);changes=[];invariants=[]
  for result in d['results']:
   old=base_by[result['document']['record_id']]
   if result['document']!=old['document']:invariants.append('源文变更')
   if len(result['rows'])!=len(old['rows']):invariants.append('边界数量变更')
   for before,after in zip(old['rows'],result['rows']):
    for k in ['unit_id','content_id','record_id','原文摘录','原始摘录','映射文章id','热度指数','互动深度指数']:
     if before.get(k)!=after.get(k):invariants.append('来源/边界/关联/指数改变：'+str(after.get('unit_id')))
    bt={t['标签路径ID'] for t in before['标签明细']};at={t['标签路径ID'] for t in after['标签明细']}
    if at!=bt or before.get('project_id')!=after.get('project_id') or before.get('项目名称')!=after.get('项目名称'):
     changes.append({'unit_id':after['unit_id'],'原文':after.get('原文摘录',after.get('原始摘录')),
      '新增标签':sorted(at-bt),'移除标签':sorted(bt-at),'原项目':before.get('项目名称'),'新项目':after.get('项目名称'),
      '打标说明':after['打标说明']})
  reports[name]={'reference':evaluate(d,ref),'projects':projects,'project_hits':sum(x['passed'] for x in projects),
    'project_total':len(projects),'changes':changes,'invariant_errors':invariants}
 target=a.root/'extra_evaluation.json';target.write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
 for name,r in reports.items():print(json.dumps({'route':name,'tag_hits':r['reference']['hit_required_tags'],
  'tag_required':r['reference']['processed_required_tags'],'wrong':r['reference']['forbidden_tag_hits'],
  'projects':r['project_hits'],'project_total':r['project_total'],'invariant_errors':r['invariant_errors']},ensure_ascii=False))

if __name__=='__main__':main()
