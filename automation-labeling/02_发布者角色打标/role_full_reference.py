import json,hashlib
from pathlib import Path
base=Path('D:/Codex/outputs/01a1349d-c76e-7b63-be36-3c8e0766deef/20261014_发布者角色各50条盲测')
out=Path(str(base)+'_全文复测')
old=json.loads((base/'codex_reference.json').read_text(encoding='utf-8'))
packets={p['sample_id']:p for p in json.loads((out/'packets.json').read_text(encoding='utf-8'))}
revisions={
 '1-23':('身份不明','文章视频内容','記得點贊關注哦','完整转写只有户型讲解及关注引导，没有明确专业身份或服务线索；修正上一轮过强的专业类参考推断。'),
 '2-29':('身份不明','作者名字','喜提新房777','只有个人化昵称与房源标题/标签，无法核实专业或普通身份；修正上一轮参考值过强的推断。'),
 '1-10':('媒体及专业机构','文章视频内容','因为我们在这行业已经四年了','房产内容创作定位与完整转写中的行业从业自述互相印证。'),
 '1-13':('媒体及专业机构','文章内容','欢迎添加我的微信，加入「中海·环宇玖章500人讨论群」并预约参观实景示范区','完整正文尾部明确提供看房群和预约服务，结合自媒体定位。'),
 '1-14':('媒体及专业机构','文章内容','欢迎扫码加入小胖看房团','完整正文尾部明确组织看房团。'),
 '1-15':('媒体及专业机构','文章内容','我们的团队是广州贝壳找房链家头部门店','完整正文尾部明确自述经纪团队、从业经验与购房咨询服务。'),
 '1-17':('媒体及专业机构','文章内容','和选房师1对1沟通','全文尾部明确选房师咨询服务。'),
 '1-18':('媒体及专业机构','文章内容','上述研究成果由克而瑞天津分析师宋筱琦','全文尾部与账号名共同支持研究机构身份。'),
 '1-20':('媒体及专业机构','文章内容','涛哥杂谈，关注房企动态，解读热门红盘','全文尾部明确房产内容创作者定位。'),
 '2-11':('媒体及专业机构','文章内容','提供一对一专业购房指导，专车接送，新房团购优惠等服务','全文尾部明确专业选房及经纪渠道服务。'),
 '2-14':('媒体及专业机构','文章内容','开发商合作渠道专属福利','完整正文尾部明确开发商合作渠道，与专业探盘账号定位相符。')}
for r in old:
 if r['sample_id'] in revisions:
  label,field,quote,reason=revisions[r['sample_id']]
  assert quote in packets[r['sample_id']]['fields'][field]
  r.update(role=label,reason=reason,evidence=[{'field':field,'quote':quote}],review_required=label=='身份不明')
 for e in r['evidence']:assert e['quote'] in packets[r['sample_id']]['fields'][e['field']]
reference=out/'codex_reference.json'
if reference.exists():raise RuntimeError('Full reference already frozen')
reference.write_text(json.dumps(old,ensure_ascii=False,indent=2),encoding='utf-8')
(out/'reference_freeze.json').write_text(json.dumps({'method':'Codex full-text re-review frozen before new Qwen run; prior Qwen results already seen, not a new blind test','reference_sha256':hashlib.sha256(reference.read_bytes()).hexdigest(),'packet_sha256':hashlib.sha256((out/'packets.json').read_bytes()).hexdigest(),'count':100,'prior_reference_label_corrections':['1-23','2-29'],'revised_evidence_ids':list(revisions)},ensure_ascii=False,indent=2),encoding='utf-8')
print('Full-text reference frozen. 2 prior over-inferred reference labels corrected; full tail evidence added for 9 further samples.')
