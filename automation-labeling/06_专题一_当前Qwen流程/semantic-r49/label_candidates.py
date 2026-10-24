"""Dictionary-wide recall candidates, never automatic positive labels.

Vocabulary routes evidence to the model; final decisions still require the full
definition, original unit, object/attribute/modality judgement and exact proof.
No IDs, source/project names or reference annotations are used as lookup keys.
"""
import re
GENERIC={'产品','公区','户型','精装','通用','整体','类型','数量','面积','尺度','功能','格局','布局','风格','整体风格','装修风格','材质与工艺','朝向','质量','性能','颜色','尺寸','标准','整体设计','空间尺度','自然景观','景观规划','会所规模','会所功能'}
SYNONYMS={
 '基础装修标准':['交付标准','交标','装修标准','精装交付'],
 '标准户型':['三房','四房','五房','三居','四居','两居','两房','一居','四室','三室','两室','五室','六室'],
 '朝向':['朝南','朝北','朝东','朝西','南向','北向','东向','西向','坐北朝南'],
 '卫生间':['一卫','两卫','二卫','三卫','四卫','五卫','六卫','主卫','客卫'],
 '客厅':['横厅','竖厅','LDK','ldk','客餐厅','家庭厅'],
 '主卧':['主套','主套房','双主套','主人房'],
 '次卧':['次卧','次套','儿童房','老人房','长辈房'],
 '特定空间':['花房','花厅','空中庭院','空中岛院','安全屋','保姆间','家政房','影音室'],
 '地下车库':['地库','地下停车','地下车库','车库','地固'],
 '大门':['主入口','门楼','门庭','门头','门厅入口'],
 '景观':['园林','绿道','水院','园景','绿植','置石','雕塑'],
 '景观小品':['雕塑','景石','置石','艺术装置'],
 '会所':['会馆','会所'],
 '整体绿化率':['绿地率','绿化率'],
 '建筑面积':['建面','平方米的户型','㎡户型','方的户型'],
 '玄关柜':['鞋柜','入户柜','门厅柜'],
 '阳台柜':['洗衣机柜','洗衣柜','家政柜'],
 '楼层':['楼栋总高','总高','层住宅','层小高','层洋房','F洋房','F高层','层建筑','顶层'],
 '采光':['采光','全明','阳光','日照','宽幅窗'],
 '通风':['通风','南北对流','南北通透','对楼'],
 '横厅/竖厅':['横厅','竖厅'],
 '外立面':['建筑','立面','幕墙','飞檐'],
}
def terms(t):
 values=[t.get(k) or '' for k in ['l3','l4','l5','emphasis']];out=set()
 for v in values:
  for word in re.split(r'[/·、，,;；]',v):
   if len(word)>=2 and word not in GENERIC:out.add(word)
  out.update(SYNONYMS.get(v,[]))
 return out
def candidates(unit,tax):
 text=unit['text'];result=[]
 for t in tax:
  hits=sorted(x for x in terms(t) if x in text)
  if hits:result.append({'tag_id':t['tag_id'],'candidate_terms':hits,'quote':'','reason':'字典及领域同义词召回候选；不等于标签成立。','evidence_ids':[]})
 return result
def missing_spatial_anchor(t,text):
 l2,l3,l4,l5=(t.get(k) or '' for k in ['l2','l3','l4','l5'])
 requirements=[]
 if l2=='公区' and l3=='外立面' and not any(x in text for x in ['外立面','建筑','外墙','幕墙','飞檐','建筑表皮']):return '本片未明确建筑外立面对象；户内玻璃或智能设备性能不自动归为外立面属性。'
 if l3=='景观' and l5=='水景' and any(x in text for x in ['水岸','河岸','江岸','湖岸','滨水']) and not any(x in text for x in ['水景','水系','水院','叠水','水池','喷泉','人造湖','中央湖','中心湖','镜面湖']):return '水岸或滨水关系未证明社区内部水景配置；不能把外围自然水体移植成住宅景观。'
 if l3=='通用' and l4=='得房率' and not any(x in text for x in ['得房率','实得率','使用率','实用率','使用面积率']):return '空间效能等未明统计口径不等同于得房率；不能替代指标。'
 if '数量' in (l4,l5):
  number=r'(?:\d+|[零一二两三四五六七八九十百千]+)'
  aliases={'次卧':['次卧','次套','儿童房','老人房','长辈房'],'主卧':['主卧','主套','主人房'],'卫生间':['卫生间','卫浴','卫'],'厨房':['厨房','中厨','西厨','厨'],'阳台':['阳台'],'特定空间':['特定空间','花房','茶室','花厅','家政间','保姆间','影音室','书房']}.get(l3,[l3])
  objects='(?:'+'|'.join(re.escape(x) for x in aliases if x)+')'
  count_unit=r'(?:个|间|处|套|部|台|樘|座|组|口|道|户|栋|位|席)?'
  if not re.search(number+r'\s*'+count_unit+r'\s*'+objects+r'|双\s*'+objects+r'|'+objects+r'\s*(?:数量)?\s*[:：为]?\s*'+number+r'\s*(?:个|间|套|处|台|部)',text):return '数量标签缺与该空间直接关联的明确计数；其他对象人数或平方米数不能隐含推成空间数量1。'
 if l2=='公区' and l3 in ['大堂','地下大堂','地下车库','社区商业']:
  requirements={'大堂':['大堂','入户大厅','单元大厅'],'地下大堂':['地下大堂','地库大堂','地下归家大厅'],'地下车库':['地库','车库','地下停车','地下车库','地固'],'社区商业':['商业','商铺','商街','底商','配套店']}[l3]
 if l2=='精装' and l3=='厨房' and '岛台' in (l4,l5):
  if not any(x in text for x in ['厨房','餐厨','中厨','西厨']):return '岛台标签缺厨房对象证据；庭院不能移作厨房。'
  requirements=['岛台','中岛','操作岛']
 if l3=='景观' and l5=='乔木':requirements=['乔木','松树','榕树','银杏','香樟','朴树','桂花树','枫树','乌桕','榉树','梧桐','栾树','白蜡树','雪松','棕榈']
 if l3=='景观' and l5=='灌木':requirements=['灌木','杜鹃','海桐','红叶石楠','黄杨','绣球','金森女贞']
 if requirements and not any(x in text for x in requirements):return '本片缺该空间或具体对象的明确证据，暂不放行；邻近对象不能替代。'
 return None

def proof_contract(t,quote):
 """Conservative final evidence gates. Negative findings never create labels.

 Scope and measurement are checked on the accepted proof, not on unrelated
 numbers elsewhere in the source or on a golden annotation.
 """
 l2,l3,l4,l5=(t.get(k) or '' for k in ['l2','l3','l4','l5'])
 number=r'(?:\d+(?:\.\d+)?|[零一二两三四五六七八九十百千]+)'
 if l2=='公区' and l3=='会所' and l4=='会所功能':
  # A list of community amenities does not make them rooms inside a club.
  listed_separately=re.search(r'(?:园区|社区|小区|项目)(?:内)?(?:配套|配置|设施)[：:].*(?:会所|会馆)\s*、',quote)
  bound_inside=re.search(r'(?:会所|会馆)(?:内|里|中|[：:]|[，,]\s*(?:内|里|其中))|(?:会所|会馆).{0,6}(?:设有|配置|包含|配备|涵盖|集成)',quote)
  if listed_separately and not bound_inside:
   return '会所与其他园区配套并列，不证明这些设施在会所内部；不能把同列社区配置移植为会所功能。'
 if l3 in ['大堂','地下大堂'] and l4=='接待管理':
  if not re.search(r'接待(?:台|处|区|室|人员|岗|服务|管理|流程)|前台|礼宾|值守|登记|访客|预约|门禁|管家|开放时间|使用条件',quote):
   return '仅有大堂或邻近设施，不证明接待管理；须有本对象的接待设施、管理做法或使用条件证据。'
 if l2=='精装' and '+' in l4:
  aliases={'油烟机':['油烟机','烟机','抽油烟机'],'燃气灶':['燃气灶','煤气灶','灶具'],'龙头':['龙头','水龙头']}
  missing=[component for component in l4.split('+') if not any(w in quote for w in aliases.get(component,[component]))]
  if missing:return '复合配置标签缺组件原文证据：'+ '/'.join(missing)+'；不能从厨电/卫浴几件套推定具体组件。'
 if l2=='户型' and l3=='通用' and l4=='建筑面积':
  if re.search(r'政策|审批|将成为绝版|预算门槛',quote) and not re.search(r'本项目|本期|本盘|提供|在售|主力户型',quote):
   return '此处面积是政策/预算阈值或市场趋势，不是目标住宅实际户型面积。'
  if not re.search(number+r'\s*(?:平方米|平方|㎡|m²|m2|平米|平|方)(?!米)',quote,re.I):
   return '户型建筑面积证据必须有本片原文数值和面积单位；裸数字或标题面积不能补作本片面积。'
 if l2=='户型' and l3=='通用' and l4=='户型编号':
  if not re.search(r'编号|代号|(?:户型|套型)\s*[:：]?\s*(?:\d{1,4})?[A-Za-z]|[A-Za-z][A-Za-z0-9-]*\s*(?:型|户型)|\d+\s*(?:号户型|号套型)|\b\d{1,4}[A-Za-z][A-Za-z0-9-]*\s*[：:]?\s*\d+\s*[房室居]',quote):
   return '裸数字户型可能是面积简称，未证明户型编号；不能同时猜为编号或补单位当面积。'
 if re.match(r'\s*(?:去现场|实地|建议|重点|需要|务必|记得).{0,12}(?:看|核实|检查|确认)',quote):
  return '证据是待现场核查的建议或检查清单，不是已观察到的产品表现。'
 if l3=='电梯厅' and l4=='梯户比':
  if not re.search(number+r'\s*梯\s*'+number+r'\s*户|\d+\s*[Tt梯]\s*\d+|梯户比\s*[:：]?\s*'+number+r'\s*[:：/]\s*'+number,quote):
   return '专梯或私梯本身未明示几梯几户；不能推定具体梯户比。'
 if l3=='大门' and l4=='尺度' and not re.search(number+r'\s*(?:米|m|M|厘米|cm|CM|毫米|mm|MM|㎡|平方米)',quote):
  return '大门尺度须有对应数值与单位，只有尺度较大或气派不成立。'
 if l2=='户型' and l3=='通用' and l4=='面宽' and re.search(r'(?:客厅|餐厅|主卧|次卧|卧室|厨房|卫生间|阳台).{0,8}(?:面宽|开间)',quote) and not re.search(r'(?:整套|户型整体|总面宽|整户|整体面宽)',quote):
  return '单一房间面宽不移作户型整体面宽，按该房间尺度标签核验。'
 if l2=='总图规划' and l3=='户数' and not re.search(r'总户数|全盘|总体|总计|合计|规划.{0,24}(?:户|席)|整个(?:社区|项目)',quote):
  if not re.search(r'(?:整体|社区|项目|全小区|全社区).{0,8}(?:仅|只有|共|为|是).{0,8}'+number+r'\s*(?:户|席)',quote):
   return '当前证据未明确全盘总户数口径；首批、加推、在售或含混套数不当项目总户数。'
 if l2 in ['户型','精装'] and re.search(r'可以作为|(?:后期|如果).{0,14}(?:改成|改为|做成)|可(?:以)?改(?:成|为)',quote):
  if not re.search(r'原始|现有|已经|已安装|已采用|开发商明确规划',quote):
   return '证据仅为个人后期装修可能/拆改方案，不是现有或开发商确定的配置。'
 if l2=='户型' and l3=='特定空间':
  special=r'特定空间|多功能|花房|花厅|家政|保姆|茶室|影音|书房|空中岛院|空中庭院|工作室|安全屋|娱乐室|收藏室|健身房'
  if re.search(r'厨房|主卧|次卧|客厅|卫生间|玄关',quote) and not re.search(special,quote):
   return '证据只描述常规房间，不能借给特定空间分支；同片另有特殊空间也须取其自身属性证据。'
 if l2=='总图规划' and l3=='楼栋数':
  batch_only=re.search(r'首开|首批|加推|本次|此次|批次|号楼',quote)
  project_total=re.search(r'总楼栋数|楼栋总数|全盘|全项目|整个项目|共规划|总体规划|合计|总计',quote)
  if batch_only and not project_total:
   return '首开、加推等批次楼栋或楼号不是项目总楼栋数；连续楼号缺分隔时也不能猜作数量或拆出编号。'
 return None

def compact_club_function_ambiguity(text):
 """Scalar table cells are adjacency, not club-function containment."""
 measured=re.search(r'(?:会所|会馆)(?:面积|规模)?\s*[:：]\s*(?:约)?\d+(?:\.\d+)?\s*(?:平方米|平米|㎡|m²|平|方)?\s*[,，|｜]?\s*(?:泳池|游泳池|健身房|瑜伽室|棋牌室)\s*[:：]',text)
 if not measured:return False
 explicit=re.search(r'(?:会所|会馆)[^。；\n]{0,30}(?:内设|内有|内含|设有|包含|包括|配备|配置|功能为|功能含)|(?:泳池|游泳池|健身房|瑜伽室|棋牌室)[^。；\n]{0,12}(?:位于|设在)(?:会所|会馆)',text)
 return not bool(explicit)

def context_contract(t,unit,proof):
 """A short proof must not detach an external referent from its local context."""
 if t.get('l3')=='会所' and t.get('l4')=='会所功能':
  if compact_club_function_ambiguity(unit['text']):
   return '紧凑资料表分别列出会所数值及设施尺寸，未证明设施位于会所内；相邻字段不建立包含关系。'
  # Status followed by an amenity list is not an explicit club containment
  # relation. Inspect the full local sentence, even when the grid proof stops
  # halfway through it. This never creates a positive label.
  for sentence in re.split(r'[。；\n]',unit['text']):
   status=re.search(r'(?:会所|会馆)[^，,。；]{0,18}(?:投入运营|开放使用|已开放|已运营)[，,]',sentence)
   explicit=re.search(r'(?:会所|会馆)(?:内|里|中|[：:]|[^，,。；]{0,12}(?:设有|配置|包含|包括|配备|涵盖))',sentence)
   if status and not explicit and proof.get('quote','') in sentence:
    return '会所运营状态与其他配套并列，未明确设施属于会所内部；不从同句共现推断会所功能。'
 if t.get('l2')!='物业形态':return None
 text=unit['text'];end=proof.get('proof_end')
 if not isinstance(end,int):return None
 context=text[max(0,end-140):end]
 markers=list(re.finditer(r'看出去|望出去|窗外|远处(?:是|的)|对面(?:是|的)|旁边(?:是|的)',context))
 if not markers:return None
 tail=context[markers[-1].end():]
 # Explicit return to this development or an explicit self-view can disambiguate.
 if re.search(r'回到|再看(?:我们|本|这个|这套)|(?:我们|本|这个|这套)(?:项目|楼盘|住宅|房子|小区|社区)|本小区|本社区|自家|自己小区',tail):return None
 return '该形态证据仍承接看出去/窗外的外部住宅对象，不能截掉前文后当作本项目物业形态。'
