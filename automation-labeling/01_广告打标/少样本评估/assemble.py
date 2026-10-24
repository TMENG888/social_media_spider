import json,csv,hashlib
from pathlib import Path
from collections import Counter
out=Path(r'D:/Codex/outputs/01a1349d-c76e-7b63-be36-3c8e0766deef/20261013_各平台广告盲测50条')
def read(n):return json.loads((out/f'{n}.json').read_text(encoding='utf-8'))
raw,packets,refs,results=map(read,['raw_samples','blind_packets','codex_reference_frozen','qwen_results'])
assert hashlib.sha256((out/'codex_reference_frozen.json').read_bytes()).hexdigest()==read('reference_freeze')['sha256']
headers=['样本编号','平台','原CSV行号','文章id','作者','标题','Codex预判','Qwen判定','对照结果','Codex依据','Codex证据','Qwen依据','Qwen证据','证据校验','调用状态','耗时秒','输入Token','输出Token','总Token','估算费用元','未知usage尝试数','文章链接','人工复核标签','人工备注']
data=[]
for r,p,ref,q in zip(raw,packets,refs,results):
 assert p['sample_id']==ref['sample_id']==q['sample_id']
 resp=q['response'] or {};m=q['metrics'];pred=resp.get('label','调用失败')
 comparison='基准待判断' if ref['label']=='待判断' else ('一致' if pred==ref['label'] else '不一致')
 evidence=lambda a:'\n'.join(f"{e.get('field','')}：{e.get('quote','')}" for e in a)
 data.append([p['sample_id'],p['platform'],p['source_row'],r.get('文章id',''),r.get('作者名字',''),r.get('文章标题',''),ref['label'],pred,comparison,ref['reason'],evidence(ref['evidence']),resp.get('reason',''),evidence(resp.get('evidence',[])),'通过' if not q['validation_issues'] else '；'.join(q['validation_issues']),m['status'],m['seconds'],m['prompt_tokens'],m['completion_tokens'],m['total_tokens'],m['estimated_yuan'],m['unknown_attempt_usage'],r.get('文章链接',''),'',''])
metrics={}
for platform in list(read('manifest')['counts'])+['全部样本']:
 subset=[r for r in data if platform=='全部样本' or r[1]==platform]
 definite=[r for r in subset if r[6]!='待判断'];tp=sum(r[6]==r[7]=='广告' for r in definite);fp=sum(r[6]=='非广告' and r[7]=='广告' for r in definite);ad=sum(r[6]=='广告' for r in definite)
 metrics[platform]={'n':len(subset),'reference_counts':dict(Counter(r[6] for r in subset)),'definite_n':len(definite),'agree':sum(r[8]=='一致' for r in definite),'tp':tp,'fp':fp,'fn':ad-tp,'tn':sum(r[6]==r[7]=='非广告' for r in definite),'qwen_uncertain':sum(r[7]=='待判断' for r in subset),'precision':tp/(tp+fp) if tp+fp else None,'recall':tp/ad if ad else None,'accuracy':sum(r[8]=='一致' for r in definite)/len(definite) if definite else None}
cost={'prompt_tokens':sum(r[16] or 0 for r in data),'completion_tokens':sum(r[17] or 0 for r in data),'total_tokens':sum(r[18] or 0 for r in data),'estimated_yuan':sum(r[19] or 0 for r in data),'unknown_usage_attempts':sum(r[20] for r in data),'request_seconds':sum(r[15] for r in data),'wall_seconds':read('qwen_run')['wall_seconds'],'call_success':sum(r[14]=='success' for r in data),'evidence_pass':sum(r[13]=='通过' for r in data)}
content={'headers':headers,'rows':data,'raw_headers':['样本编号','原CSV行号']+[k for k in raw[0] if k!='source_row'],'raw_rows':[[p['sample_id'],r['source_row']]+[r[k] for k in raw[0] if k!='source_row'] for p,r in zip(packets,raw)],'manifest':read('manifest'),'metrics':metrics,'cost':cost,'run':read('qwen_run')}
(out/'comparison_data.json').write_text(json.dumps(content,ensure_ascii=False,indent=2),encoding='utf-8')
with (out/'各平台广告识别逐条对照.csv').open('w',encoding='utf-8-sig',newline='') as f:
 w=csv.writer(f);w.writerow(headers);w.writerows(data)
print(json.dumps({'metrics':metrics,'cost':cost,'disagreements':[(r[0],r[6],r[7],r[11]) for r in data if r[8]=='不一致'],'evidence_issues':[r[0] for r in data if r[13]!='通过']},ensure_ascii=False,indent=2))
