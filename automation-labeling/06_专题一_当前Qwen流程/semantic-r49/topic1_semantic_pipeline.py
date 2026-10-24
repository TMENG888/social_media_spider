"""Topic1-only candidate. Uses existing production ApiRunner; no reference access.

Stages: lossless semantic partition / full-taxonomy label / evidence+omission review.
No source ID, reference tag list, or golden slicing boundaries in prompts/rules.
"""
import json,re,copy
VERSION='t1-semantic-evidence-r49-complete-proof-tokens'
ROLES=['品牌、区域公司、项目官方','媒体及专业机构','普通账号','身份不明']
LEVELS=['I0 无创新判断','I1 来源宣称创新','I2 有升级迭代证据','I3 有同类差异证据']
INNOVATIONS=['产品创新','设计创新','工艺创新','技术集成创新','无明确创新类型']
BASE='''你负责全国地产设计产品力监测专题一，只依据给定原文及字典；不是专题二口碑标注。不使用外部知识补事实。
目标是住宅项目本身的产品做法，营销文章也可提取，文章不是事实已兑现的保证。周边自然资源、外部案例、酒店不作为住宅自身配置。
标签须同时满足空间对象、属性和限定条件，不靠关键词。否定/假设/想象/提问不当作已配置事实；但字典收录的缺失议题可按定义处理。
标题和全文能补同盘身份，不能把别段配置、数值、评价搬到本片。原文引用严格逐字连续，不可纠错、加省略号、整合不连续句。
原文明示优先，字典产品系/别名仅作为经营主体候选，必须核实具体同城同盘；品牌不等于经营主体。主体未知填空，不填待判断。不凭账号名称判断发布者机构身份。
不输出验收状态、互动深度指数、情绪评分。所有JSON字符串值不含Markdown。'''
PARTITION=BASE+'''
先读全文再做语义切片，暂不打标签。按项目/空间/连贯产品做法划分，不按标签分片，不因无精确标签丢有效产品信息。
规划指标、建筑风格、产品布局、绿色建筑等独立主题须分片；同一主题的相关指标保留一起，不机械按句或字数拆。入口风格和场地标高主题独立时分开。
生成完整分区(从全文首字到末字，无遗漏)。start_quote只返回该段开头8~20个连续字符，严禁返回整段；occurrence指该短串在全文出现的第几次，不是段落序号！绝大多数为1。下一段起点就是本段终点。
首段必须从全文第0字符开始。不可把景观、会所、整套户型、主卧、次卧等不同空间统归成一片；在各自可独立理解的主题转换处切开。同一空间同一做法的相关尺寸不分片。
每段deliver:住宅产品信息为true，即使标签可能为空；广告尾注、想象、重复总述或纯区位配套上下文为false，并说出原因。勿把绿建认证等无现成标签的有效产品信息排除。
practice用一句话浓缩本片对象、数值、做法和限定，不增添效果或推测。非交付段practice可以为空。
创新枚举：产品创新/设计创新/工艺创新/技术集成创新/无明确创新类型；等级I0 无创新判断/I1 来源宣称创新/I2 有升级迭代证据/I3 有同类差异证据。高端修辞不是创新。无证据I0。
身份字段必须给最短证据和字段(标题/正文/文章标签)，证据不足留空；发布者角色枚举：品牌、区域公司、项目官方/媒体及专业机构/普通账号/身份不明。
JSON格式 {"publisher_role":"身份不明","publisher_evidence":"","units":[{"start_quote":"原文起点","occurrence":1,"deliver":true,"reason":"","brand":"","project":"仅内部案名或地块描述，不发明正式名","city":"","practice":"","innovation":"无明确创新类型","level":"I0 无创新判断","innovation_reason":"本片无迭代或同类差异证据","identity_evidence":""}]}。
'''
LABEL=BASE+'''
全文分区已经冻结，不改切片边界。逐片遍历给定全部适用字典，不漏掉不常见分支。每标签给本片中最短充分连续证据quote(需涵盖对象/属性/必要限定)和简短reason。
没有精确标签时数组为空，但保留产品切片。标签ID必须来自字典。宽泛标签和细分标签分别按完整定义判断；满足两项才都标，不自动去重父项也不自动下钻。
注意以下通用边界：户均面积不当户型建面、客餐厅面积不当客厅面积；部分户型未知不抹掉已知四房/大三房等结构；社区停车数不自动成为地下车库数量；地基/场地标高不当大门高度或质量；围墙材料不当建筑外立面材料；入口风格不当外立面风格；绿化泛述不推乔木花卉；五恒等系统不自动拆成新风地暖空调；无小高不能当有小高；不做高低配不否定已明确纯洋房。
JSON {"units":[{"index":1,"labels":[{"tag_id":"VOC-xxxx","quote":"","reason":""}]}]}，每段都返回，未交付段labels可为空。数字index从1起。
'''
REVIEW=BASE+'''
独立复核给定模型草案，返回完整最终标签数组，不只返回差异。边界冻结不可改变。
按全部字典检查两种错误：有原文明示且完整匹配却漏标；对象或属性不匹配、否定/想象误当事实造成误标。不要为追求多标而硬凑，也不要因审慎漏掉字典本来允许的宽泛标签。
标签必须证明此片住宅对象+完整属性。公区气派、尺寸不等于质量；高差/标高不等于门楼高度；围墙石材不是建筑立面；外部河湖不是园区水景；宽泛绿化不细分植物；引用或比较对象配置不移植。
具体产品做法摘要必须覆盖本片已明确事实且不增添数值，不将宣传或拟配置改为已兑现；保留未知限制。请给每片完整、精简的最终practice，校正空值和漏信息，不要堆砌标签名。
情景已明确且标签定义允许时勿过度排除，例如已知房间结构尽管具体平面未公示仍可记户型；物理配置明确的宽泛标签不需要更细空间证明。
JSON {"units":[{"index":1,"practice":"","labels":[{"tag_id":"VOC-xxxx","quote":"最短充分本片原文","reason":""}]}],"audit_note":"仅主要更正点，无需自我评价"}。
'''
def metadata(doc):
 r=doc.get('row',{})
 return {k:r.get(k,'') for k in ['文章标题','文章标签','作者名字','作者主页链接','平台','关键词']}
def obj(props):return {'type':'object','properties':props,'required':list(props),'additionalProperties':False}
def arr(x):return {'type':'array','items':x}
S={'type':'string'}
PARTITION_SCHEMA=obj({'publisher_role':{'type':'string','enum':ROLES},'publisher_evidence':S,'units':arr(obj({'start_quote':{'type':'string','minLength':1,'maxLength':24},'occurrence':{'type':'integer','minimum':1},'deliver':{'type':'boolean'},'reason':S,'brand':S,'project':S,'city':S,'practice':S,'innovation':{'type':'string','enum':INNOVATIONS},'level':{'type':'string','enum':LEVELS},'innovation_reason':S,'identity_evidence':S}))})
def call(runner,doc,system,payload,phase,schema=None):
 response,m=runner.call(system,payload,doc,phase,response_schema=schema)
 if m['status']=='failed_json':
  # One bounded format recovery. API attempts and billed invalid response stay
  # in the original runner audit; authentication failures are never retried here.
  response,m=runner.call(system+'\n只返回所要求的完整JSON对象，不输出Markdown或长推演。',{'input':payload,'response_error':'上次输出不是完整有效JSON，请完整重答，不延续上次文本。'},doc,phase+'JSON恢复',response_schema=schema)
 if m['status']!='success' or not isinstance(response,dict):raise RuntimeError(f'{phase} failed: {m.get("error", "invalid response")}')
 return response
def occurrences(text,q):
 starts=[];i=0
 while q and (j:=text.find(q,i))>=0:starts.append(j);i=j+1
 return starts
def materialize_partition(doc,draft):
 text=doc['text'];units=draft.get('units');assert isinstance(units,list) and units,'Empty partition'
 points=[]
 for u in units:
  q=u.get('start_quote','');hits=occurrences(text,q);n=u.get('occurrence',1)
  if not isinstance(n,int) or n<1 or n>len(hits):raise ValueError(f'Invalid exact start anchor: {q[:40]}')
  points.append(hits[n-1])
 if points[0]!=0 or points!=sorted(set(points)):raise ValueError('Partition starts must strictly increase from 0')
 for i,u in enumerate(units):
  u['index']=i+1;u['start']=points[i];u['end']=points[i+1] if i+1<len(points) else len(text);u['text']=text[u['start']:u['end']]
  if type(u.get('deliver'))!=bool:raise ValueError('deliver must be bool')
  if u.get('innovation') not in INNOVATIONS or u.get('level') not in LEVELS:raise ValueError('Invalid innovation enum')
  if u['deliver'] and not str(u.get('practice','')).strip():raise ValueError('Missing product practice')
 return units
def attach_labels(units,data,tax):
 mapping={u['index']:u for u in units};seen=set();lookup={t['tag_id']:t for t in tax}
 if not isinstance(data.get('units'),list):raise ValueError('Missing label units')
 for v in data['units']:
  n=v.get('index')
  if n not in mapping or n in seen:raise ValueError('Unknown or duplicate unit index')
  seen.add(n);u=mapping[n];labels=v.get('labels');assert isinstance(labels,list)
  if 'practice' in v:
   if u['deliver'] and not str(v['practice']).strip():raise ValueError('Review empty practice')
   u['practice']=v['practice']
  got=[];used=set()
  for label in labels:
   tid=label.get('tag_id');q=label.get('quote','');reason=label.get('reason','')
   if tid not in lookup or not q or q not in u['text'] or not reason:raise ValueError(f'Invalid exact label evidence {n} {tid} {q[:40]}')
   if tid in used:continue
   used.add(tid);got.append(label)
  u['labels']=got
 if seen!=set(mapping):raise ValueError('Some units not returned')
 return units
def compact_tax(tax):return [{k:t.get(k) for k in ['tag_id','l1','l2','l3','l4','l5','emphasis','instruction']} for t in tax]
def atoms(u):
 # Localisation grid, NOT the semantic partition. Selection of consecutive IDs
 # retrieves a single verbatim source span, so the model cannot rewrite quotes.
 return [{'id':i+1,'start':m.start(),'end':m.end(),'text':m.group()} for i,m in enumerate(re.finditer(r'.{1,24}?(?:[，,。！？!?；;]|$)|.{24}',u['text'],re.S))]
def grid_payload(units):
 return [{'index':u['index'],'deliver':u['deliver'],'brand':u.get('brand'),'project':u.get('project'),'practice':u.get('practice'),'text':u['text'],'evidence_grid':atoms(u),'labels':u.get('labels',[])} for u in units]
GRID_LABEL=BASE+'''
逐片核对给定全部标签字典，覆盖其完整适用范围。deliver只是上一步建议，不能用它跳过字典核验；总图规划、楼栋数、容积率、物业形态同样是住宅产品信息，不限于户内。允许同片多标签但每个必须证明本片的正确空间对象及属性。未知/否定/想象不当作已配置。
不要重写证据文字。每片evidence_grid是定位用的小段编号，并非语义切片。用evidence_ids选择连续编号，程序自动取原文；选足以证明对象、属性及限定的最短连续范围。
返回JSON {"units":[{"index":1,"labels":[{"tag_id":"VOC-xxxx","evidence_ids":[1,2],"reason":"该片对象和属性为何满足标签定义"}]}]}。每片返回，未命中空数组。evidence_ids必须是该片网格整数编号，不是字符偏移；多段证据程序会取其首尾之间的完整原文，不会拼接。
宽泛标签和细分标签独立核验，不默认互斥也不默认下钻。停车位数量可以支持车位，但不等于地下车库数量；四房/大三房等结构支持标准户型，即使具体图未公示；纯同一业态组合可记录产品组合，非必须高低配。
客餐厅合计面积不能套成客厅面积。一般尺寸不是面积；空间明确不能跨玄关客厅公区等对象套用。大门风格非立面风格；围墙石材非建筑立面材料；地基抬升非门楼高度或质量；外部河湖非园区水景；景观总体气氛不是具体乔灌花。
分批推出几套或几号楼不是项目总户数/总楼栋数。仅有某厨房存在不代表明确厨房数量。只有餐厨功能说明不等于数量。不能把会所体系自动标为会所中健身房。
'''
GRID_REVIEW=GRID_LABEL+'''
你在做第二次独立审查。草案可能漏标也可能多标：对全部字典查漏，再逐项核对空间/属性/数值/否定限定，返回完整最终labels，不只增量。无证据删去，有充分证据才保留；不为凑标签覆盖率而标。不要修改切片边界或实践摘要。
'''
def complete_evidence_span(text,start,end,definition):
 # Grid IDs are localisation hints, not permission to cut a quantity/unit or
 # dictionary phrase in half. Only complete tokens ALREADY OVERLAPPING the
 # chosen range; never search a separate sentence to manufacture support.
 # This is not an entailment check and does not shorten overlong evidence.
 import label_candidates
 if not 0<=start<end<=len(text):raise ValueError('Invalid evidence span')
 measurement=r'\d+(?:\.\d+)?(?:[-–—~～至/]\d+(?:\.\d+)?)?(?:万|亿)?\s*(?:平方米|平方千米|平方公里|平方厘米|平方毫米|厘米|毫米|㎡|m²|m2|km²|km2|cm²|cm2|mm²|mm2|mm|cm|km|米|m|方(?!向)|户(?!型|数|均)|栋(?!数)|层(?!高|数)|个|套(?!型)|席|%|％)?'
 ranges=[(m.start(),m.end()) for m in re.finditer(measurement,text,re.I)]
 ranges.extend((m.start(),m.end()) for m in re.finditer(r'[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*',text))
 for term in label_candidates.terms(definition):
  ranges.extend((m.start(),m.end()) for m in re.finditer(re.escape(term),text))
 while True:
  old=(start,end)
  for a,b in ranges:
   if a<start<b:start=a
   if a<end<b:end=b
  if old==(start,end):return start,end

def attach_grid(units,data,tax):
 converted={'units':[]};by={u['index']:u for u in units}
 definitions={t['tag_id']:t for t in tax}
 for u in data.get('units',[]):
  if u.get('index') not in by:raise ValueError('Unknown unit index')
  target=by[u['index']];grid={a['id']:a for a in atoms(target)};labels=[]
  for x in u.get('labels',[]):
   ids=x.get('evidence_ids')
   if not isinstance(ids,list) or not ids or any(type(i)!=int or i not in grid for i in ids):raise ValueError(f'Invalid evidence IDs {u["index"]} {x.get("tag_id")}')
   ids=sorted(set(ids));span_ids=list(range(ids[0],ids[-1]+1))
   a,b=grid[ids[0]]['start'],grid[ids[-1]]['end']
   original=(a,b)
   a,b=complete_evidence_span(target['text'],a,b,definitions.get(x['tag_id'],{}))
   proof={'tag_id':x['tag_id'],'quote':target['text'][a:b],'reason':x.get('reason',''),'evidence_ids':span_ids,'proof_start':a,'proof_end':b}
   if original!=(a,b):proof['evidence_span_completion']={'grid_start':original[0],'grid_end':original[1],'kind':'overlapping_original_tokens_only'}
   labels.append(proof)
  converted['units'].append({'index':u['index'],'labels':labels})
 return attach_labels(units,converted,tax)
def unit_payload(units):return [{k:u.get(k) for k in ['index','text','deliver','reason','brand','project','city','practice','labels']} for u in units]
PURE_PARTITION='''你是住宅产品文章语义分段器，只做分段，不做标签、摘要、身份判断。
按项目、空间或独立产品主题转换划分，不按标签或字数分段。规划指标可合一段；建筑外立面、产品布局、绿色建筑认证是不同主题，不能混合。
景观、会所、整套户型、客餐厅、主卧、次卧如果各自有可独立理解的具体做法应分段。同一空间关联数值不拆成碎片。开场、广告尾注亦须处理。
返回JSON {"cuts":[{"quote":"每段开头连续原文短串","occurrence":1,"theme":"本段主题"}]}。quote只用于定位起点，建议8至16字，不必引用整段。下一起点为前段终点。首段从全文第一个字符开始。occurrence是quote在全文出现次数，不是段落编号！'''
CUT_REVIEW='''核对住宅产品文章的语义分区草案，只修正分段，不做标签或摘要。返回完整最终切点JSON {"cuts":[{"quote":"每段开头原文短串","occurrence":1,"theme":"本段主题"}]}。
每段一个可独立理解的空间产品做法或主题，不能把规划指标、立面风格/材料、户型布局、绿色建筑认证混一片。户型总览和各空间若有独立完整配置，按主题划分；同一空间关联数值不机械拆分。
入口形象/围墙/建筑立面分别处理；标高与入口风格独立时分开。景观与会所分开，正文具体产品做法与无信息广告结尾分开。不要按标签产生重复段。
保留无标签产品段，不丢全文首尾。多段同一主题只在连续且同一对象时可合并。quote是原文起点短锚而非整段全文，occurrence不是顺序号。'''
ANNOTATE=BASE+'''
按给定冻结分区逐片判断字段，不得修改边界。所有index必须返回。原文/标题可补同盘身份但不能搬产品配置；同一住宅项目的品牌可有据承接，不必每段重复品牌词。
deliver为住宅自身有效产品信息(含无标签的绿建认证)；纯区位、重复概述、想象、广告结尾false。实践摘要覆盖本片明确做法、数值与限制，不添未明示的城市或效果。
经营主体仅明示或同城同盘证实才填；字典产品系/别名只是候选。publisher_role只按原文身份证据判，作者名字本身不够。
返回JSON {"publisher_role":"身份不明","publisher_evidence":"","units":[{"index":1,"deliver":true,"reason":"","brand":"","entity":"","entity_evidence":"","project":"","city":"","practice":"","innovation":"无明确创新类型","level":"I0 无创新判断","innovation_reason":"本片无迭代或同类差异证据","identity_evidence":""}]}。
创新类型枚举产品创新/设计创新/工艺创新/技术集成创新/无明确创新类型；等级I0 无创新判断/I1 来源宣称创新/I2 有升级迭代证据/I3 有同类差异证据。无具体创新依据为I0，不因高端修辞给创新。
'''
def resolve_cuts(doc,response):
 text=doc['text'];cuts=response.get('cuts');assert isinstance(cuts,list) and cuts
 points=[];registry=[]
 for c in cuts:
  original=c.get('quote','');q=original;hits=[]
  # A model may echo an overlong anchor and alter a later whitespace. Only an
  # unambiguous, verbatim PREFIX can locate its start. No fuzzy/normalised text.
  while len(q)>=min(6,len(original)):
   hits=occurrences(text,q)
   if hits:break
   q=q[:-1]
  if not hits:raise ValueError('No exact source anchor '+original[:24])
  n=c.get('occurrence',1)
  if len(hits)==1:pos=hits[0]
  elif isinstance(n,int) and 1<=n<=len(hits):pos=hits[n-1]
  else:raise ValueError('Ambiguous repeated source anchor '+q[:24])
  points.append(pos);registry.append({'quote':q,'model_quote':original,'occurrence':hits.index(pos)+1,'theme':c.get('theme','')})
 # Cuts are positions in a source, not an ordered model narrative. Canonicalise
 # only uniquely resolved, distinct offsets; never invent a boundary or merge
 # ambiguous duplicates. Keep the model order in the internal audit.
 if len(set(points))!=len(points):raise ValueError('Duplicate partition start')
 if points!=sorted(points):
  order=sorted(range(len(points)),key=lambda i:points[i])
  for i,p in enumerate(registry):p['model_order']=i+1;p['canonicalised_order']=True
  points=[points[i] for i in order];registry=[registry[i] for i in order]
 if points[0]>0:
  points.insert(0,0);registry.insert(0,{'quote':text[:min(16,points[1])],'model_quote':None,'occurrence':1,'theme':'未分区开场，交由字段步骤判断，不直接排除'})
 return [{'index':i+1,'start':a,'end':points[i+1] if i+1<len(points) else len(text),'text':text[a:points[i+1] if i+1<len(points) else len(text)],'start_quote':registry[i]['quote'],'start_occurrence':registry[i]['occurrence'],'theme':registry[i]['theme'],'anchor_audit':registry[i]} for i,a in enumerate(points)]
LOCAL_CUT_REVIEW='''只复核给定原文片段的语义主题边界，不打标签、不写摘要、不判断身份。
原文可能无换行，把规划参数、建筑立面、园林、物业服务、会所、户型、精装连写。逐主题检查：各自具有可独立理解的产品事实时分开；同一空间的关联数值或一个连贯做法不要机械拆成一词一片。不能为标签拆片或按字数切片。
完整保留片段首尾和所有文字。代词/连接词需要前句才能成立时保留必要上下文，不复制或重写。没有独立转换时仅返回一个切点。
返回JSON {"cuts":[{"quote":"每段开头8至16个连续原文字符","occurrence":1,"theme":"本段主题"}]}。首个quote必须从输入第一个字符开始。occurrence是该短串在本片段内出现的次数，不是段落序号。只返回JSON。'''

def topic_refinement_candidates(text):
 # Routing only: overlapping vocabulary never creates a cut or a label.
 patterns={
  '规划参数':r'容积率|总户数|总栋数|楼栋数|规划.{0,12}栋|\d+栋.{0,8}住宅',
  '建筑立面':r'外立面|建筑风格|幕墙|建筑表皮',
  '园林景观':r'园林|景观|水景|草坪|风雨连廊',
  '会所':r'会所|会馆',
  '户型空间':r'户型|主卧|次卧|卫生间|客餐厅|[三四五六两二][房室]',
  '精装设备':r'精装|厨电|地暖|新风|中央空调|智能家居',
 }
 return [name for name,pattern in patterns.items() if re.search(pattern,text)]

def parent_delivery_qualifiers(doc,unit):
 review=unit.get('local_partition_review',{})
 if not review.get('split'):return []
 start,end=review['parent_start'],review['parent_end'];raw=doc['text'][start:end]
 # A statement explicitly scoped to "装标" applies to the configuration
 # paragraph, not merely the closest item after a newly introduced cut.
 pattern=r'(?:涉及装标|上述装标|以上装标|本段(?:装修|交付)标准)[^。；\n]*?(?:以[^。；\n]*?合同[^。；\n]*?为准|以写入合同为准)'
 return [{'start':start+m.start(),'end':start+m.end(),'quote':m.group()} for m in re.finditer(pattern,raw)]

def refine_topic_partition(doc,units,runner):
 from concurrent.futures import ThreadPoolExecutor
 def review(parent):
  topics=topic_refinement_candidates(parent['text'])
  if len(topics)<2:return [parent]
  payload={'text':parent['text']};previous=None;error=None
  for attempt in range(2):
   answer=call(runner,doc,LOCAL_CUT_REVIEW,payload if not attempt else {**payload,'previous':previous,'validation_error':error},'专题一局部跨主题切片复核' if not attempt else '专题一局部切片合同修复')
   try:
    children=resolve_cuts({'text':parent['text']},answer)
    if children[0]['anchor_audit'].get('model_quote') is None:raise ValueError('首切点必须明确从输入片段第0字符开始')
    for child in children:
     child['start']+=parent['start'];child['end']+=parent['start']
     child['local_partition_review']={'parent_start':parent['start'],'parent_end':parent['end'],'candidate_topics':topics,'split':len(children)>1}
    if ''.join(c['text'] for c in children)!=parent['text']:raise ValueError('局部复核必须逐字完整覆盖输入')
    return children
   except (ValueError,AssertionError,KeyError,TypeError) as e:previous=answer;error=str(e)
  raise ValueError('局部主题切片合同修复失败：'+str(error))
 with ThreadPoolExecutor(max_workers=3) as pool:
  groups=list(pool.map(review,units))
 refined=[u for group in groups for u in group]
 for i,u in enumerate(refined,1):u['index']=i
 return refined

def label_units_exhaustive(doc,units,tax,runner):
 import exhaustive_labels as ex
 import label_candidates as recall
 from concurrent.futures import ThreadPoolExecutor,as_completed
 merged={u['index']:[] for u in units};table_audit=[];verdicts=[];tm={t['tag_id']:t for t in tax}
 with ThreadPoolExecutor(max_workers=4) as pool:
  fs={pool.submit(ex.classify_group,doc,units,tax[a:a+24],runner):a for a in range(0,len(tax),24)}
  for f in as_completed(fs):
   a=fs[f];labels,data=f.result();table_audit.append({'start':a,'result':data})
   for i,ps in labels.items():merged[i].extend(ps)
 for u in units:merged[u['index']].extend(recall.candidates(u,tax))
 for i in merged:
  merged[i]=sorted({p['tag_id']:p for p in merged[i]}.values(),key=lambda p:p['tag_id'])
 verified={u['index']:[] for u in units}
 with ThreadPoolExecutor(max_workers=4) as pool:
  fs={pool.submit(ex.verify_pair,doc,u,p,tm[p['tag_id']],runner):(u['index'],p['tag_id']) for u in units for p in merged[u['index']]}
  for f in as_completed(fs):
   i,tid=fs[f];proof,verdict=f.result();verdicts.append({'index':i,'tag_id':tid,'verdict':verdict})
   if proof:verified[i].append(proof)
 for u in units:u['labels']=sorted(verified[u['index']],key=lambda p:p['tag_id'])
 joint=[]
 with ThreadPoolExecutor(max_workers=4) as pool:
  fs={pool.submit(ex.joint_review,doc,u,tax,runner):u for u in units if u['labels']}
  for f in as_completed(fs):
   u=fs[f];kept,check=f.result();joint.append({'index':u['index'],'before':u['labels'],'review':check});u['labels']=sorted(kept,key=lambda p:p['tag_id'])
 return merged,{'engine':ex.VERSION,'table_audit':sorted(table_audit,key=lambda x:x['start']),'verdicts':sorted(verdicts,key=lambda x:(x['index'],x['tag_id'])),'joint_review':sorted(joint,key=lambda x:x['index'])}

LOCAL_PRACTICE='''只处理给定住宅文章的一个语义片段，不能借用标题或其他段落的配置。
决定本片是否有住宅自身的有效产品做法；总图、风格、景观、户型、材料、绿建均有效，即使无字典标签也保留。纯区位、施工进度泛述、开发商资质、销售战绩、联系方式、预约邀请和无新增配置的泛赞美不交付。
practice只概括unit_text中明确的产品对象、做法、数值及状态；标题只用于辨认对象，不向摘要搬运任何配置。没有本片证据的事实不写。明确区分外部公园/河湖与住宅自身园林。拟配置/样板展示/想象不改成已交付事实。
保留数字和原单位，不做换算，也不补全文其他段的数字；套内各空间的总面积不写成单个空间面积。保留不确定或未公开限制。一个切片多个关联事实可用一句话概括，不能只挑标题。
创新仅按本片证据：来源宣称首创I1、明确迭代I2、同类差异I3，否则I0。不凭高端修辞判创新。
JSON {"deliver":true,"reason":"本片为何有或无产品信息","practice":"只概括本片，非交付可空","innovation":"无明确创新类型","level":"I0 无创新判断","innovation_reason":"本片无升级或同类差异证据"}。
innovation只能是产品创新/设计创新/工艺创新/技术集成创新/无明确创新类型；level只能是I0 无创新判断/I1 来源宣称创新/I2 有升级迭代证据/I3 有同类差异证据。'''

def local_practice(doc,u,runner,force_product=False,feedback=None,scope_review=False):
 payload={'unit_text':u['text']}
 if feedback:payload['fidelity_feedback']=feedback
 if force_product:payload['verified_current_unit_labels']=u.get('labels',[])
 system=LOCAL_PRACTICE+('本片已经由本片原文证据确认为产品信息。deliver须为true，仅按unit_text概括配置；即使标签证据来自片段，也不能使用其他段落事实。' if force_product else '')
 if scope_review:system+='本次独立复核专题一范围：住宅自身产品不等于仅住宅楼内部，还包括项目自建/自带的社区商业、架空层、园区配建和公共空间。住宅自带商业街区是自身产品，不能改称外部城市配套；与周边城市商场、外部学校分开。自建商业的面积、设计及在建/招商状态可构成有效做法，不要求必须同时写户型/建筑材料或命中字典标签。同段有外部配套时，仅摘要已有证据的自有部分。是否交付仍独立判断，不能因词语召回即强判true。'
 if feedback:system+='本次为忠实性合同修复。fidelity_feedback的每一项均须纠正，优先于常识补全：删除指出的新增品牌及无据事实，品牌不规范时原样照录或省略；原文注明合同为准、未公开/未公示的限定须原样保留在practice中。不要重复被指出的错误。'
 previous=None;error=None
 for attempt in range(2):
  repair_payload={**payload,'previous':previous,'validation_error':error,'repair_rule':'逐字保留unit_text已明示的数字，不借标题数字，不求和、不推算、不换单位；删除未在unit_text逐字出现的数字及其新增结论。'}
  v=call(runner,doc,system,payload if not attempt else repair_payload,'专题一当前切片产品摘要' if not attempt else '专题一当前切片摘要合同修复')
  try:
   if type(v.get('deliver'))!=bool or v.get('innovation') not in INNOVATIONS or v.get('level') not in LEVELS:raise ValueError('Invalid local summary enum')
   if v['deliver'] and not str(v.get('practice','')).strip():raise ValueError('Empty local practice')
   if force_product and not v['deliver']:raise ValueError('本片已由本片标签证据确认产品，不能整片排除')
   source_numbers=set(re.findall(r'\d+(?:\.\d+)?',u['text']))
   added=set(re.findall(r'\d+(?:\.\d+)?',v.get('practice','')))-source_numbers
   if added:raise ValueError('摘要数字不在当前切片中，请仅保留当前切片明示且不换算的数值：'+','.join(sorted(added)))
   return v
  except (ValueError,KeyError,TypeError) as e:previous=v;error=str(e)
 if str(error).startswith('摘要数字不在当前切片中'):
  # Preserve the source rather than guess how concatenated ASR/table numbers
  # should be split. This is an explicit extractive fallback, not a successful
  # abstractive summary, and it never changes labels or original excerpts.
  return {'deliver':v['deliver'],'reason':'摘要数字合同两次未通过；本片改为原文摘录式做法，未拆分含混数字或补全单位。',
          'practice':u['text'] if v['deliver'] else '',
          'innovation':'无明确创新类型','level':'I0 无创新判断','innovation_reason':'摘录式容错不推定创新。',
          'summary_fallback':{'kind':'verbatim_current_unit','validation_error':error,'rejected_practice':v.get('practice','')}}
 raise ValueError('Local practice contract failed after bounded repair: '+str(error))

PRACTICE_FIDELITY='''核查一个住宅原文切片的摘要及创新结论，仅凭unit_text，不允许借用其他段落、标题或外部常识。
摘要可浓缩、换自然语言表达，但对象、品牌专名、数值、单位、条件和状态须获当前原文支持。不能擅自把不规范品牌词改成另一个品牌，不能把样板/拟建写成已交付，不能丢弃“具体未公示”“或同等品牌/以合同为准”等实质限定，不能将多个空间总面积改成单个空间面积。ASR不确定专名可原样保留或省略，不凭常识补品牌。省略非核心事实不直接判不忠实，但改变事实范围和确定性应指出。
创新只能依据本片明示首创/迭代/具体比较；普通高端修辞不支持创新。I0不要求额外创新证据。
I1只表示来源自称，不表示已核实真实首创；本片明确“首创”可记I1，不因为同片其他ASR错字质疑来源可信度而要求外部实证。
ASR不清楚的风格、专名或配置不得自行纠错为一个更像常识的确定词；可省略或写“原文称”。不能把宣传性的生活感受专业化成未明示的技术性能。数字相同但新增㎡、米、层等单位仍是新增事实；不同交房时间/明暗卫等原文冲突须保留冲突或不确定性，不能单选一个当事实。纯检查建议不是已观察的表现。
必须逐个核对摘要中的全部事实分句，每项claim须为practice的连续原文，按顺序合起来覆盖全部practice正文；source_quote须为unit_text中支持本项的连续原文。无证据时source_quote可空且supported=false。不得仅核对其中一两句就放过其余句子。innovation另外核对，不把它混入摘要claim。
JSON {"supported":true,"issues":[],"claims":[{"claim":"摘要分句原文","source_quote":"本片最短充分连续证据","supported":true,"reason":"简短说明对象、单位和状态是否一致"}]}；不支持时supported=false，issues为不受支持的摘要原句及原因。只检查此片，不对标签提出修改。'''

def check_claim_coverage(text,practice,verdict):
 claims=verdict.get('claims')
 if not isinstance(claims,list) or not claims:raise ValueError('Summary review requires all factual claims')
 cursor=0
 def substantive(s):return re.sub(r'[\s\W_]+','',s,flags=re.UNICODE)
 for c in claims:
  claim=c.get('claim','');quote=c.get('source_quote','')
  if not claim or type(c.get('supported'))!=bool:raise ValueError('Invalid summary claim')
  start=practice.find(claim,cursor)
  if start<0 or substantive(practice[cursor:start]):raise ValueError('Summary claim coverage gap or rewritten claim')
  if c['supported'] and (not quote or quote not in text):raise ValueError('Summary claim lacks verbatim local evidence')
  if quote and quote not in text:raise ValueError('Summary review rewrote source evidence')
  cursor=start+len(claim)
 if substantive(practice[cursor:]):raise ValueError('Summary claim coverage tail missing')
 if any(not c['supported'] for c in claims) and verdict.get('supported'):raise ValueError('Unsupported claim hidden by overall approval')

CONFIG_BRANDS=['嘉格纳','博世','杜拉维特','高仪','唯宝','弗兰卡','科勒','汉斯格雅','摩恩','乐家','大金','日立','威能','三菱','松下','西门子','美诺','伊莱克斯','卡萨帝','格力','美的','海尔','东芝','约克','开利','特灵','霍尼韦尔','飞利浦','摩根','欧瑞博','华为','小米','3M','立邦','多乐士','圣象','安信','方太','老板','奥普','欧派']
def lexical_fidelity_issues(text,practice):
 import summary_evidence
 issues=['摘要新增原文未出现的配置品牌：'+b for b in CONFIG_BRANDS if b.lower() in practice.lower() and b.lower() not in text.lower()]
 issues.extend(summary_evidence.explicit_owner_conflicts(text,practice))
 issues.extend(summary_evidence.personal_proposal_conflicts(text,practice))
 issues.extend(summary_evidence.colisted_container_conflicts(text,practice))
 issues.extend(summary_evidence.unsupported_facility_expansions(text,practice))
 # Match number AND unit, not independent bags of number tokens. Never infer
 # an omitted ASR unit or borrow a unit belonging to another quantity.
 unit=r'(?:平方米|平方千米|平方公里|厘米|毫米|㎡|m²|米|方|平(?!台|面)|户(?!型)|栋|幢|层|个|套|席|%|％)'
 for m in re.finditer(r'\d+(?:\.\d+)?\s*'+unit,practice):
  value=re.sub(r'\s+','',m.group())
  if value not in re.sub(r'\s+','',text):issues.append('摘要数值与单位组合未在本片明示：'+value)
 if any(x in practice for x in ['交付','交房','交标']) and not any(x in text for x in ['交付','交房','交标']):issues.append('原文仅为展示或当前状态，摘要不得新增交付/交房/交标结论。')
 if re.search(r'以.{0,12}合同.{0,6}为准',text) and '合同' not in practice:issues.append('须保留装标以合同为准这一实质限定。')
 if any(x in text for x in ['未公示','未公布','未公开']) and not any(x in practice for x in ['未公示','未公布','未公开','尚未明确']):issues.append('保留原文未公开/未公示的限制，不能只留下已知部分而抹去未知状态。')
 # Mixed sanitary daylight claims must not collapse into an unconditional
 # one-sided fact. Ambiguous ASR stays ambiguous rather than being "fixed".
 dark=r'暗厕|暗卫';bright=r'明厕|明卫|明侧'
 if re.search(dark,text) and re.search(bright,text):
  has_dark=bool(re.search(dark,practice));has_bright=bool(re.search(bright,practice))
  uncertain=bool(re.search(r'不确定|待核|存疑|冲突|分歧|未明确|说法不一',practice))
  if not uncertain and ((has_dark!=has_bright) or re.search(r'非暗|不是暗|并非暗|均为明|全部明',practice)):
   issues.append('本片并存明暗卫表述且对象或条件未充分消歧；不能单选一种或将暗卫反写为非暗卫，须保留差异或不确定性。')
 return issues

def excluded_product_candidate(text):
 # Routing only: an independent local model still decides delivery scope.
 # Self-owned commercial/other facilities must not disappear merely because
 # the paragraph also lists outside amenities, or no exact tag was selected.
 owner=r'(?:自带|自建|自有|社区内|小区内|项目内|园区内|本项目规划|本小区规划)'
 facility=r'(?:商业|商街|商铺|幼儿园|托育|会所|会馆|园林|景观|架空层|绿建|绿色建筑|车库|停车|运动场|活动场)'
 return bool(re.search(owner+r'[^。；\n]{0,35}'+facility,text))

def review_excluded_product(doc,u,runner):
 if u['deliver'] or not excluded_product_candidate(u['text']):return None
 answer=local_practice(doc,u,runner,feedback=[
  '范围复核而非已判定应交付：区分住宅自身配建/自带的具体产品与外部城市配套。'
  '同段混有外部配套不能排除已明确的自身产品；自身商业体等即使无精确标签也可交付。'
  '如只有外部配套、规划义务而无住宅自身产品做法，仍应不交付。摘要不移植外部配置。'],scope_review=True)
 audit={'previous_deliver':u['deliver'],'previous_reason':u.get('reason'),'decision':answer}
 u.update(answer);u['scope_recheck']=audit
 return audit

def source_scope_qualifiers(text):
 # Only an explicitly global design/delivery disclaimer. Do not propagate
 # local exceptions, prices, units, or product configurations across slices.
 return [{'start':m.start(),'end':m.end(),'quote':m.group()}
         for m in re.finditer(r'[^。\n]{0,12}(?:本文|文中|上述)(?:建筑|园林|场景|设计|所示|所涉|图片)[^。\n]{0,150}(?:意境参考|设计意向|示意)[^。\n]{0,150}',text)
         if re.search(r'交付.{0,20}(?:合同|实景)|(?:合同|实景).{0,12}为准',m.group())]

def preserve_qualifiers(u):
 # Preserve explicit source qualifiers deterministically before model review.
 # This never adds external claims or changes raw excerpts/labels.
 qualifiers=[]
 if re.search(r'以.{0,12}合同.{0,6}为准',u['text']) and '合同' not in u['practice']:qualifiers.append('具体以合同为准')
 if any(x in u['text'] for x in ['未公示','未公布','未公开']) and not any(x in u['practice'] for x in ['未公示','未公布','未公开','尚未明确']):
  qualifiers.extend(m.group() for m in re.finditer(r'[^，。；()\n（）]{0,18}(?:未公示|未公布|未公开)[^，。；()\n（）]{0,12}',u['text']))
 if qualifiers:
  u['summary_qualifier_patch']={'before':u['practice'],'source_qualifiers':qualifiers}
  u['practice']+='（'+'；'.join(qualifiers)+'）'

def review_practice(doc,u,runner):
 import summary_evidence
 preserve_qualifiers(u)
 def check():
  literal_issues=lexical_fidelity_issues(u['text'],u['practice'])
  if literal_issues:return {'supported':False,'issues':literal_issues,'decision_method':'literal_fidelity_guard'}
  return summary_evidence.review(doc,u,runner,call,atoms(u))
 before={k:u[k] for k in ['practice','innovation','level','innovation_reason']}
 first=check()
 if first['supported']:return {'initial':first,'repaired':False}
 repaired=local_practice(doc,u,runner,force_product=True,feedback=first['issues'])
 u.update({k:repaired[k] for k in before})
 preserve_qualifiers(u)
 final=check()
 if not final['supported']:
  # Explicit, auditable extractive fallback after a bounded semantic repair.
  # Never accept an unsupported paraphrase or secretly copy a gold summary.
  u['summary_fallback']={'kind':'verbatim_current_unit','rejected_practice':u['practice'],'issues':final['issues']}
  u.update(practice=u['text'],innovation='无明确创新类型',level='I0 无创新判断',innovation_reason='摘录式容错不推定创新。')
  u['reason']=(u.get('reason','')+'；摘要忠实性修复仍有无据主张，保留本片原文，不补事实。').strip('；')
  return {'initial':first,'repaired':True,'before':before,'final':final,'fallback':u['summary_fallback']}
 return {'initial':first,'repaired':True,'before':before,'final':final}
def process_document(doc,tax,business,runner,label_engine='exhaustive'):
 if doc['topic']!='全国地产设计产品力监测' or doc['kind']!='文章':raise ValueError('Topic1 articles only; Topic2 untouched')
 common={'metadata':metadata(doc),'text':doc['text']}
 cut=call(runner,doc,PURE_PARTITION,{'text':doc['text']},'专题一纯语义切点')
 cut=call(runner,doc,CUT_REVIEW,{'text':doc['text'],'draft':cut},'专题一语义主题边界复核')
 try:units=resolve_cuts(doc,cut)
 except (ValueError,AssertionError,KeyError) as e:
  cut=call(runner,doc,CUT_REVIEW,{'text':doc['text'],'draft':cut,'validation_error':str(e)},'专题一分区合同修复')
  units=resolve_cuts(doc,cut)
 units=refine_topic_partition(doc,units,runner)
 draft=call(runner,doc,ANNOTATE,{'source':common,'units':units,'business_dictionary':business},'专题一字段独立生成')
 fields={u['index']:u for u in draft.get('units',[])}
 if set(fields)!=set(u['index'] for u in units):raise ValueError('Missing annotated units')
 for u in units:
  u.update({k:v for k,v in fields[u['index']].items() if k not in ['index','start','end','text','start_quote']})
  if type(u.get('deliver'))!=bool or u.get('innovation') not in INNOVATIONS or u.get('level') not in LEVELS:raise ValueError('Invalid field enum')
  if u['deliver'] and not u.get('practice'):raise ValueError('Empty practice')
 # Summary is generated with only the current raw interval, never the whole
 # document. This prevents otherwise well-formed cross-paragraph numbers.
 from concurrent.futures import ThreadPoolExecutor,as_completed
 with ThreadPoolExecutor(max_workers=4) as pool:
  local=list(pool.map(lambda u:local_practice(doc,u,runner),units))
 for u,v in zip(units,local):u.update(v)
 with ThreadPoolExecutor(max_workers=3) as pool:
  list(pool.map(lambda u:review_excluded_product(doc,u,runner),units))
 source_context={'metadata':common['metadata'],'text':doc['text']}
 if label_engine=='exhaustive':labels_before_review,review=label_units_exhaustive(doc,units,tax,runner)
 elif label_engine=='legacy':
  merged={u['index']:[] for u in units}
  for offset in range(0,len(tax),64):
   group=tax[offset:offset+64];group_units=grid_payload(units)
   for v in group_units:v['labels']=[]
   payload={'source':source_context,'units':group_units,'taxonomy':compact_tax(group),'scope':'仅判断本批字典，其他标签由其他批次处理；不要凭记忆返回本批以外ID。'}
   label=call(runner,doc,GRID_LABEL,payload,'专题一分字典网格标注'+str(offset//64+1))
   try:attach_grid(units,label,group)
   except (ValueError,AssertionError,KeyError) as e:
    label=call(runner,doc,GRID_LABEL,{**payload,'previous':label,'validation_error':str(e)},'专题一分字典合同修复'+str(offset//64+1));attach_grid(units,label,group)
   for u in units:merged[u['index']].extend(u.get('labels',[]))
  for u in units:u['labels']=merged[u['index']]
  labels_before_review=copy.deepcopy({u['index']:u['labels'] for u in units});selected={x['tag_id'] for u in units for x in u['labels']}
  payload={'source':source_context,'units':grid_payload(units),'taxonomy':compact_tax([t for t in tax if t['tag_id'] in selected])}
  review=call(runner,doc,GRID_REVIEW,payload,'专题一网格证据及漏标复核')
  try:attach_grid(units,review,tax)
  except (ValueError,AssertionError,KeyError) as e:
   review=call(runner,doc,GRID_REVIEW,{**payload,'previous':review,'validation_error':str(e)},'专题一网格复核合同修复');attach_grid(units,review,tax)
 else:raise ValueError('Unknown labeling engine')
 # A valid product label must not disappear because an earlier coarse scope
 # filter excluded the whole paragraph. Request the missing fields explicitly.
 rescued=[u for u in units if not u['deliver'] and u['labels']]
 if rescued:
  for u in rescued:
   v=local_practice(doc,u,runner,force_product=True)
   if not v.get('practice'):raise ValueError('Labeled product missing practice')
   u['deliver']=True;u['reason']='已由标签证据复核确认本项目产品信息；不因同段带外部配套整片排除。'
   u.update({k:v[k] for k in ['practice','innovation','level','innovation_reason'] if k in v})
 with ThreadPoolExecutor(max_workers=3) as pool:
  fs={pool.submit(review_practice,doc,u,runner):u for u in units if u['deliver']}
  for f in as_completed(fs):fs[f]['summary_fidelity_audit']=f.result()
 qualifiers=source_scope_qualifiers(doc['text'])
 taxmap={t['tag_id']:t for t in tax};rows=[];traces=[]
 for u in units:
  if not u['deliver']:continue
  tagjson=[]
  for x in u['labels']:
   t=taxmap[x['tag_id']];tagjson.append({'标签路径ID':t['tag_id'],'标签编号':t.get('source_number'),'一级标签':t['l1'] or None,'二级标签':t['l2'] or None,'三级标签':t['l3'] or None,'四级标签':t['l4'] or None,'五级标签':t['l5'] or None,'标签强调方向':t['emphasis']})
  i=len(rows)+1
  rows.append({'unit_id':doc['record_id']+f'-Q{i:03}','content_id':doc['record_id'],'证据序号':i,'原文摘录':u['text'],'证据定位':f'{doc["field"]}字符[{u["start"]},{u["end"]})','品牌组':u.get('brand',''),'经营主体':'','项目':u.get('project',''),'城市':u.get('city',''),'打标说明':json.dumps(u['labels'],ensure_ascii=False),'标签明细':tagjson,'标签强调方向':';'.join(dict.fromkeys(t['标签强调方向'] for t in tagjson)),'具体产品做法':u['practice'],'创新类型':u['innovation'],'创新等级':u['level'],'创新依据':u['innovation_reason'],'热度指数':doc['row'].get('热度指数'),'备注':u.get('reason',''),'起点':u['start'],'终点':u['end'],'发布者角色':draft.get('publisher_role','身份不明')})
  traces.append({'起点':u['start'],'终点':u['end'],'原文证据':u['text'],'标签证据与理由':u['labels']})
  if qualifiers:
   rows[-1]['备注']+='；来源全文设计/交付限定（非本片配置证据）：'+'；'.join(q['quote'] for q in qualifiers)
  parent_qualifiers=parent_delivery_qualifiers(doc,u)
  if parent_qualifiers:
   u['parent_delivery_qualifiers']=parent_qualifiers
   rows[-1]['备注']+='；原段共用装修交付限定（非本片配置证据）：'+'；'.join(q['quote'] for q in parent_qualifiers)
 result={'document':doc,'rows':rows,'traces':traces,'semantic_partition':units,'full_source_partition':{'units':units},'publisher_role':draft.get('publisher_role'),'publisher_evidence':draft.get('publisher_evidence'),'pipeline_version':VERSION,'audit_note':review.get('audit_note'),'label_audit':review,'labels_before_review':labels_before_review,'complete':True}
 result['source_scope_qualifiers']=qualifiers
 return result
