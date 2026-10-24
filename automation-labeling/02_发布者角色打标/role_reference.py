import json,hashlib
from pathlib import Path
out=Path('D:/Codex/outputs/01a1349d-c76e-7b63-be36-3c8e0766deef/20261014_发布者角色各50条盲测')
packets=json.loads((out/'packets.json').read_text(encoding='utf-8'))
labels=['品牌、区域公司、项目官方','媒体及专业机构','普通账号','身份不明']
# Independently reviewed Codex reference, recorded before Qwen calls. Not verified account identity.
codes1=[3,2,3,1,1,3,3,1,1,1,1,3,1,1,1,1,1,1,0,1,3,1,1,3,1,1,1,1,1,3,3,0,1,1,1,3,1,1,3,1,1,3,1,1,1,1,3,3,1,3]
codes2=[1,3,2,3,1,1,1,2,1,2,1,0,1,1,1,1,1,1,3,1,3,1,1,1,1,1,1,1,1,1,1,3,1,1,3,3,1,1,1,3,1,1,1,1,1,1,1,1,1,1]
special={
'1-02':('文章内容','我当年中石油、中石化笔试全过','以个人求职经历分享备考经验，无机构或服务身份线索。'),
'1-05':('文章内容','欢迎来找我看房','个人署名且直接提供看房预约服务，归销售专业账号，不归官方机构账号。'),
'1-08':('作者名字','北方号写字楼商业公寓整栋买卖','账号明确以商业地产买卖为业务。'),
'1-09':('文章内容','在保利做了多年销售','明确自述销售从业身份；个人销售归专业类。'),
'1-11':('文章内容','迎欢预约潘潘一起品鉴','联系方式账号结合个人看房预约服务，判断为销售专业账号。'),
'1-13':('文章内容','致力于做最值得信赖的新房自媒体','明确自述新房自媒体角色。'),
'1-23':('文章视频内容','記得點贊關注哦','专业户型讲解及关注引导，按房产内容创作者推断；建议人工核验。'),
'1-25':('文章视频内容','感兴趣的联系我看房','个人主动提供房源看房服务。'),
'1-27':('文章视频内容','带客户','看房从业账号，转写明确提及带客户。'),
'1-28':('文章视频内容','客户找我买这个房子','明确为客户代理购房。'),
'1-32':('文章视频内容','可以来到咱们的收楼处','项目同名账号以项目方第一人称接待，推断项目官方；未核验认证。'),
'1-35':('文章视频内容','169万八千的特价','房源销售报价与探房账号相互支持，归专业销售类。'),
'2-01':('文章内容','安排10年选房师1v1帮您free选房哦','明确提供选房师及专车看房服务。'),
'2-03':('文章内容','个人转租','自述个人转租，按普通个人账号，不因租赁广告归机构。'),
'2-05':('文章内容','感兴趣可以私信预约看房','个人署名且承接看房服务，归销售专业类。'),
'2-07':('文章内容','代理机构名称：北京麦田房产经纪有限公司','明确列出房产经纪代理机构。'),
'2-09':('文章标题','找我高额返费55%','返佣销售服务账号，不归开发商官方。'),
'2-10':('文章内容','欢迎大家各抒己见，相互探讨学习啦','个人昵称及实地体验优缺点讨论，无从业或引流线索。'),
'2-11':('文章内容','北京在售楼盘几乎都有合作','跨项目合作与优惠带看服务，属于经纪渠道。'),
'2-12':('文章内容','关注“建发海晏”微信公众号','项目同名公众号承接项目自身预约、恭候莅临，推断官方；未核验主体认证。'),
'2-15':('作者名字','新房售楼处直通车','售楼处资讯/导流账号，不把转载的“开发商直营”说明当账号官方认证。'),
'2-16':('文章内容','我们专注探房','明确自述专业施工进展拍摄服务。'),
'2-18':('文章内容','接待不少看海淀改善的朋友','明确以接待客户的身份提供选房分析。'),
'2-23':('文章标签','京建房产自媒体','标签明示房产自媒体。'),
'2-38':('作者名字','华润地产刘经理','个人地产经理署名，归销售从业类，不等同机构官方账号。')}
reference=[]
for p in packets:
 d,i=map(int,p['sample_id'].split('-'));code=(codes1 if d==1 else codes2)[i-1];f=p['fields']
 field='作者名字';quote=f[field]
 reason=['账号名称明确为房企区域公司，推断机构官方；未核验认证。','账号名称与房产专业内容支持媒体/从业者角色，未核验资质。','个人生活/经历分享，未见职业或机构身份线索。','现有字段不能可靠区分普通个人、销售渠道或项目官方，不凭推广文案强猜。'][code]
 if p['sample_id'] in special:field,quote,reason=special[p['sample_id']]
 if code==3:reason+=' 需补充账号简介或认证主体。'
 evidence=[] if not quote else [{'field':field,'quote':quote}]
 assert all(e['quote'] in f[e['field']] for e in evidence)
 reference.append({'sample_id':p['sample_id'],'role':labels[code],'reason':reason,'evidence':evidence,'review_required':code==3 or code==0 or p['sample_id'] in ['1-23','1-12','1-15','1-38','2-27','2-29','2-39']})
ref=out/'codex_reference.json'
if ref.exists():raise RuntimeError('Already frozen; do not silently replace baseline')
ref.write_text(json.dumps(reference,ensure_ascii=False,indent=2),encoding='utf-8')
(out/'reference_freeze.json').write_text(json.dumps({'method':'Codex independent pre-annotation, not human gold','reference_sha256':hashlib.sha256(ref.read_bytes()).hexdigest(),'packet_sha256':hashlib.sha256((out/'packets.json').read_bytes()).hexdigest(),'count':100},ensure_ascii=False,indent=2),encoding='utf-8')
print('Frozen independent reference for 100 records. No Qwen results used.')
