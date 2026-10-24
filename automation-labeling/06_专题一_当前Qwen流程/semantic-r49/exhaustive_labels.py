"""Auditable exhaustive taxonomy classification, independent from references."""
import copy,json
import topic1_semantic_pipeline as base
import label_candidates as recall
VERSION='t1-exhaustive-table-r4-path-object-scope'
SYSTEM='''你是住宅产品配置核验员。只核验给定字典，不做摘要或切片。
对本批每一个tag_id都必须返回一行checks，不能漏行。例子不是唯一允许值；按完整路径及定义判断，而非只匹配例子中的词。
每个标签必须同时满足：1.住宅项目自身正确空间对象；2.原文明示符合该属性的事实；3.不是被否定、假设或想象的配置。未知就不标，但不能把已明确的事实因为其他信息未知一并抹掉。
对每个候选先明确被标的物理对象，再核验属性。大门≠围墙≠立面；地基标高≠大门挑高；园林≠大堂；地库≠地下大堂；会所≠社区商业；室外庭院≠厨房岛台。相邻出现不代表属于同一对象。
户型通用标签可记录该住宅套内各空间的采光/通风等特征，不要求必须出现“全屋”字样；局部精确标签与通用标签都满足时可以同时命中。社区总体停车没有指明地下时，不能标地下车库分支。
总图规划、建筑风格、景观、户型、绿色建筑都是可保留的产品信息，deliver只是上一步建议，不能据此跳过检查。纯洋房等单一业态组合可记产品组合，不只高低配。定性“绿化率高”可记录整体绿化率，但不能编百分比。
总面积不当局部面积；客餐厅合计面积不当客厅独立面积；户均面积不当户型建面；首批套数不当全盘户数；出现厨房不等于明确厨房数量。价格未明毛坯/精装不得擅自归类。
“四房”“三居”“两卫”即为明确的套型/卫生间数量信息，不要求同时给齐几房几厅几卫，局部未公示不能抹掉已知。套内主卧明确朝南可以记主卧朝向，不因同片谈全屋户型而遗漏。
风格标签须有设计语汇、构图、空间形态或搭配关系；只有一种建材或某设施的存在，不自动等于风格。景观错落/疏密搭配可表现景观设计风格；会所明确对标酒店的设计取向可表现会所整体风格，不把酒店设施移植进本会所。
泛草木不自动细分乔木灌木花卉；花朵雕塑是雕塑不是植物；有水景不等于总景观面积。仅说豪华不等于工程质量。
视频文字可能有同音错字，结合语义消歧，但不能借此发明空间，如不明确有“大堂”就不从“地库”造地下大堂。不得改原始证据文字；不能确认的事实不补。
各切片有本地evidence_grid，用evidence_ids选择本片的编号，程序自动取得首尾之间的连续原文。不要输出或改写原文quote。
返回JSON {"checks":[{"tag_id":"本批每一ID","present":false,"matches":[]},{"tag_id":"命中ID","present":true,"matches":[{"unit_index":1,"object":"原文实际空间或对象","attribute":"原文明示的属性或数值","evidence_ids":[1,2],"reason":"一句话为何同时匹配对象和属性"}]}]}。
present必须与matches是否非空一致。无命中返回false和空数组；命中只返回有据matches，不能把理由中说“不标”的标签放进命中数组。无须为false写理由。
'''
VERIFY='''独立核验一个住宅产品标签。只根据给定本片原文和完整字典判断，不参考任何参考答案。标签只有空间对象、属性、限定三者均匹配才选中。
大门/围墙/地基/建筑立面是不同对象；地库不等于地下大堂；会所不等于社区商业；室外庭院不是厨房岛台；泛草木不是明确乔木灌木；雕塑不是活体花卉。
标签通用采光/通风可记录套内任一空间的明确表现，不必须写全屋；例子不穷尽所有表达。总体停车未说明地下不能用于地下车库；分批套数不是全盘户数；价格没说明毛坯或精装则不能强分。
不得把局部未知抹掉已明确的事实。套型只明确几房仍可支持标准户型，保留未知；纯洋房组合也是产品组合。定性绿化率可以标但不补数值。客餐厅面积不当客厅面积。
风格必须体现设计语汇/构图/空间形态或搭配，不是只要有建材就有风格；仅提玻璃幕墙这一材料，不足以判外立面风格。室内采光或通风明确即可以记对应通用标签，不要求全文全屋都采光好。
按下面JSON逐项判断，不输出长推演：{"object_matches":true,"attribute_matches":true,"modality_matches":true,"selected":true,"evidence_ids":[1],"reason":"简短证据结论"}。
selected只有在前三项都为true才为true；若不满足，selected=false并给原因，evidence_ids为空即可。证据编号来自本片evidence_grid，程序原样取证，不生成quote。
'''
CLARIFICATIONS='''
完整标签路径限定属性；定义中的泛化措辞和示例不能覆盖路径本身。例如路径是面宽时须有横向开间尺寸，只有建筑面积不成立；路径是数量时须有明确数字/数词/双套等计数，只有“有某空间”或单数名词不能隐含推为1。
“标准户型”的房、厅、卫是可分别记录的套型信息，不是三者必须齐全的联合门槛；已明确三房/四居等即满足，另注明未知的细部，不因具体平面图未公开而否认已知房数。
客厅类型是家庭厅/会客厅等用途或种类；横厅/竖厅属于格局，不因其存在再附加类型。客餐厨一体化(LDK)明确客厅与餐厨的空间组织，属于客厅格局，不要求额外写横厅。套内朝向须有房屋或开间的明确方向关系；“南向多开间”可记，不从对流通风、窗外风景或双阳台反推套内/阳台朝向。主套房属于主卧对象，主套明确方向可记主卧朝向。
风格不强制要求“中式/现代”等命名：明确的设计主题、空间组织、人工布景层次疏密或自然式构图也可满足；“艺术园林”等明确设计取向按来源陈述保留，不等于外部已证实。只有美好、豪华等泛赞美或单项材料仍不足。会所明确酒店化对标及下沉空间形态可记录来源所述整体风格，不移植被对标酒店的具体设备。
景观小品包括造型置石/景石及雕塑，不限座椅灯具；普通草木不算小品。主入口明确玻璃、金属等自身材质可以记大门材料；同段独立雕塑的手工工艺不移植给门楼。
景观面积须为社区景观整体统计口径；水池/中央湖单一设施面积不能当总景观面积。外部公园、河流、自然季节变化，不移植成社区园林面积或四季搭配。“可实地看看楼间距”没有说明其数值/疏密/关系，不是实际楼间距配置。
每条证据必须能回答“谁的哪个属性”，同片相邻的量词、材料、工艺、朝向不能跨对象借用。无法区分对象的ASR不确定词不能编造配置，但可靠上下文可识别同音对象。最后判断必须遵守以上完整规则，不能在reason承认事实满足后仍机械排除。
面积/尺寸类标签需要本片实际的对应数值、单位及计量对象；“所有面积以建筑面积为准”只是一句计量口径，不能单独当作产品建筑面积配置。
不得在复核时添加字典没有的联合门槛。户型采光明确“环幕采光”“高采光”等就是采光表现，定义举例“全明/日照时间”不是必须条件，不要求全部房间全明；只是说窗外景色好则不成立。车位配比明确住宅配套车位配置，可支持宽泛车位标签，不要求同时给位置或总数，但不能代替地下车库数量。
布局模式的兵营式/围合式/点群式仅为示例，不排斥原文明示的行列式、一字排列等其他总图组织方式；不能把户内格局借给总图。楼间距的开阔/紧密等定性空间关系可记录且不补米数；单纯邀请“看楼间距”仍不成立。
风格可见特征包括公建化的建筑设计取向、峡谷式或立体式的景观组织；不应误判为只有中式/现代才是风格。它们须确实修饰对应建筑立面或住宅景观，不把外部酒店设施搬入项目，也不把单一建材自动当风格。
'''
SYSTEM+=CLARIFICATIONS
VERIFY+=CLARIFICATIONS
VERDICT_SCHEMA=base.obj({k:{'type':'boolean'} for k in ['object_matches','attribute_matches','modality_matches','selected']} |
 {'evidence_ids':base.arr({'type':'integer','minimum':1}),'reason':{'type':'string','minLength':1,'maxLength':240}})
def decode(units,data,tax):
 expected={t['tag_id'] for t in tax};by={u['index']:u for u in units};checks=data.get('checks')
 if not isinstance(checks,list):raise ValueError('Missing checks table')
 seen=set();labels={i:[] for i in by}
 for c in checks:
  tid=c.get('tag_id')
  if tid not in expected or tid in seen:raise ValueError('Unknown/duplicate tag '+str(tid))
  seen.add(tid)
  if type(c.get('present'))!=bool or not isinstance(c.get('matches'),list) or c['present']!=bool(c['matches']):raise ValueError('Inconsistent present/matches '+tid)
  for hit in c['matches']:
   i=hit.get('unit_index')
   if i not in by:
    # An unaddressed draft is a retrieval candidate only. Route it to every
    # real interval rather than turn a made-up address into accepted evidence.
    for target in by:labels[target].append({'tag_id':tid,'quote':'','evidence_ids':[],'reason':'草案地址不合法，仅作逐片独立核验候选。','draft_address_invalid':True})
    continue
   reason=hit.get('reason') or '草案对象/属性未完整说明，仅作独立核验候选。'
   # This is a recall proposal, not accepted evidence. A wrong draft address is
   # explicitly retained as unverified; only the independent check can label.
   temp=copy.deepcopy(by[i]);temp['index']=1
   try:
    base.attach_grid([temp],{'units':[{'index':1,'labels':[{'tag_id':tid,'evidence_ids':hit.get('evidence_ids'),'reason':reason}]}]},tax)
    proposal=temp['labels'][0]
   except ValueError:proposal={'tag_id':tid,'quote':'','reason':reason,'evidence_ids':[],'draft_address_invalid':True}
   labels[i].append({**proposal,'object':hit.get('object'),'attribute':hit.get('attribute')})
 if seen!=expected:raise ValueError('Missing explicit decisions '+','.join(sorted(expected-seen)))
 for i,ps in labels.items():
  unique={}
  for x in ps:
   tid=x['tag_id']
   if tid not in unique or len(x['quote'])<len(unique[tid]['quote']):unique[tid]=x
  labels[i]=list(unique.values())
 return labels
def classify_group(doc,units,tax,runner):
 grid=base.grid_payload(units)
 for u in grid:
  u['labels']=[]
  # Candidates must be based on raw intervals, not possibly erroneous summaries.
  u.pop('practice',None)
 payload={'source_metadata':base.metadata(doc),'source_text':doc['text'],'units':grid,'taxonomy':base.compact_tax(tax)}
 result=base.call(runner,doc,SYSTEM,payload,'专题一逐项字典核验')
 try:labels=decode(units,result,tax)
 except (ValueError,KeyError,AssertionError) as e:
  result=base.call(runner,doc,SYSTEM,{**payload,'previous':result,'validation_error':str(e)},'专题一逐项核验合同修复')
  labels=decode(units,result,tax)
 return labels,result
def verify_pair(doc,unit,label,tax,runner):
 veto=recall.missing_spatial_anchor(tax,unit['text'])
 if veto:return None,{'object_matches':False,'attribute_matches':False,'modality_matches':False,'selected':False,'evidence_ids':[],'reason':veto,'decision_method':'spatial_evidence_guard'}
 payload={'source_metadata':base.metadata(doc),'unit_text':unit['text'],'evidence_grid':base.atoms(unit),'label_definition':base.compact_tax([tax])[0]}
 previous=None;error=None;evidence_errors=[]
 for attempt in range(2):
  answer=base.call(runner,doc,VERIFY+definition_notes([tax]),payload if not attempt else {**payload,'previous':previous,'validation_error':error},'专题一单标签对象属性核验' if not attempt else '专题一单标签判定合同修复',schema=VERDICT_SCHEMA if attempt else None)
  try:
   keys=['object_matches','attribute_matches','modality_matches','selected']
   if any(type(answer.get(k))!=bool for k in keys) or answer['selected']!=all(answer[k] for k in keys[:3]) or not answer.get('reason') or len(answer['reason'])>240:raise ValueError('Invalid independent verdict：四个布尔值须一致，reason须为不超过240字的简短结论，不输出推演。')
   if answer['selected']:
    temp=copy.deepcopy(unit);temp['index']=1
    base.attach_grid([temp],{'units':[{'index':1,'labels':[{'tag_id':tax['tag_id'],'evidence_ids':answer.get('evidence_ids'),'reason':answer['reason']}]}]},[tax])
    veto=recall.proof_contract(tax,temp['labels'][0]['quote']) or recall.context_contract(tax,unit,temp['labels'][0])
    if veto:return None,{**answer,'selected':False,'attribute_matches':False,'reason':veto,'decision_method':'positive_evidence_contract','model_verdict':answer}
    return temp['labels'][0],answer
   return None,answer
  except (ValueError,KeyError,AssertionError) as e:
   previous=answer;error=str(e)
   if (all(type(answer.get(k))==bool for k in ['object_matches','attribute_matches','modality_matches','selected'])
       and answer.get('selected') is True and error.startswith(('Invalid evidence IDs','Invalid exact label evidence'))):
    evidence_errors.append({'answer':answer,'error':error})
 if len(evidence_errors)==2:
  return None,{'selected':False,'object_matches':False,'attribute_matches':False,'modality_matches':False,
               'evidence_ids':[],'reason':'两次提案均无合法本片原文证据，拒绝该标签，不以标题配置补证。',
               'decision_method':'bounded_invalid_evidence_rejection','rejected_attempts':evidence_errors}
 raise ValueError('Single-label contract failed after bounded repair: '+str(error))

JOINT='''复核同一住宅原文片段中已拟选的多个标签，只检查本片；不要引用标题或其他段落事实，不增加新标签。
逐项明确真实物理对象、实际属性、状态限定，再决定保留。特别检查同一数值、材料、工艺、朝向被移植给相邻的不同空间；同片出现某对象不代表本片所有属性都属于它。用其他候选标签对照区分对象，不以多标为目标。
客餐厅合计面积≠客厅独立尺度；主卧朝南≠整套户型朝南；南北对流≠双阳台朝向；有横厅格局≠家庭厅等客厅类型；门楼尺寸≠会所挑高；花朵雕塑手工工艺≠门楼材料。窗外外部植物园四季景象≠社区四季搭配。想象或单纯愿景不是已确定配置。
返回JSON {"checks":[{"tag_id":"每个给定ID恰好一次","keep":true,"actual_object":"该属性实际属于什么","attribute":"原文实际属性","evidence_ids":[1],"reason":"不超过120字的结论"}]}。不保留时keep=false、evidence_ids可空。保留时必须选择本片证据编号，禁止改写引文。'''
JOINT+=CLARIFICATIONS

def definition_notes(tax):
 notes=set()
 for t in tax:
  if t.get('l3')=='装修标准' and t.get('l4')=='基础装修标准':notes.add('本片逐项列举墙面、柜体、设备等具体装修内容，并明确其属于交付标准，即可记录该片已明示的基础装修范围；不要求一片同时列齐全屋、全部房间或完整配置表。只说精装/一线品牌而无任何具体内容，或仅样板展示且未明交标，不能据此推为明确基础交标。该宽泛标准项和已获独立证据支持的具体空间配置可同时成立。')
  if t.get('l3')=='通用' and t.get('l4')=='面宽':notes.add('本任务标注来源谈及了什么，不认证来源尺寸为客观实测。明确修饰户型整体的横向面宽可以用米、厘米或毫米表示，m/cm/mm均是尺寸单位；不能因单位不是米、数值看似异常就声称原文没有数值。对象、属性和原文明示数值单位齐备时，即使数值违反常识或疑似ASR单位错误，也仍记录来源所述面宽议题，在reason明确注明“来源数值或单位疑似异常，按原文保留，未经外部核实”；不能仅凭建筑常识删掉来源明确谈及的议题。不换算、不修正数值，也不把建筑面积、阳台尺寸或单一房间面宽借给整户。原文本身未明确对象、单位或仅是假设时仍不标，不靠常识补齐。')
  if t.get('l3')=='车位':notes.add('宽泛车位项记录住宅配套停车配置，明确车位配比即为有效配置；不能额外要求同时写地下/地面或总数，亦不能据配比标地下车库总数。')
  if t.get('l3')=='主卧' and t.get('l4')=='数量':notes.add('双主卧/双主套为明确两处主卧数量；不能仅因未使用阿拉伯数字而排除。普通双套房不一定是双主卧，仍核对象。')
  if t.get('l2')=='精装':notes.add('配置事实与交付保证分开核验：本片明确实景已有、已安装或已施工的对应设备/柜体及做法，可记录来源所述配置，保留实景/样板/施工范围，不等于全盘交付标准；“宣传或样板展示不等于实际交付”不是把所有实景配置排除。字典例子的品牌、型号不是额外必填联合门槛；明确的规格、配置或做法可单独成立。仅建议添置/假设拆改不当已有配置。本片先明确精装交付再提样板房，不抹掉已有交标；同片有建议也不抹掉另一句已存在事实。')
  if t.get('l3')=='玄关' and t.get('l4')=='玄关柜':notes.add('进门处或入户处的鞋柜可属于玄关柜，按其实际位置判断；不要求原文恰好使用“玄关柜”三个字。')
  if t.get('l3')=='厨房' and t.get('l4')=='岛台':notes.add('原文明确厨房已经有岛台，即是岛台配置事实；定性小/大、能否用餐是该岛台的表现，不强制再要求品牌、型号、数字尺寸或交付保证。只有“可以加岛台”的建议不当已配置。')
  if t.get('l3')=='阳台' and t.get('l4')=='阳台柜':notes.add('阳台上的洗衣机柜属于该空间柜体；已规划好不等于已安装，记录来源状态。不能把另一空间的洗衣柜移植到阳台。')
  if t.get('l3') in ['大堂','地下大堂'] and t.get('l4')=='接待管理':notes.add('有星级大堂、私宴厅、酒廊不证明大堂接待管理。须有该大堂的接待台/前台等设施，或接待人员、执行方式、使用条件/时间等明确管理证据；不把邻近会所配套移植给大堂。')
  if t.get('l3')=='通用' and t.get('l4')=='建筑面积':notes.add('本片明确住宅户型的建筑面积即可记录：单值、多户型面积列表、面积区间均合法，不要求单一固定值，不因同时列房数而删面积。须有本片实际数值及面积单位；裸数字未带面积单位时不补单位，也不猜作户型编号。可靠语境可识别ASR同音对象，但原摘录不改；不添加原文没有的具体户型。')
  if t.get('l2')=='物业形态':notes.add('先识别物业形态实际修饰哪个住宅；“看出去是另一项目的别墅区，那个经典独栋别墅”仍在解释外部景观，不变成本项目别墅。邻近一句的转述、代词、赞美需承接正确的最近明确对象，不因孤立引文省略案名就换对象。')
  if t.get('l3')=='卫生间' and t.get('l4')=='干湿分离':notes.add('“可以作为/后期可以做四分离”是个人装修可能方案，不等于现有布局；与开发商明确规划采用的方案区分。无现有或正式规划依据时不标已配置。')
  if t.get('l3')=='卫生间' and t.get('l4')=='数量':notes.add('不同户型可以分别有不同卫生间数量，不要求全盘或本片所有户型统一为一个数值。户型记录明确各自房厅卫数，已证明该对象的卫生间数量；需保留各户型对应关系，不因存在两种卫数而全部拒绝。不明确具体对象的数量仍不能借用。')
  if t.get('l3')=='客厅' and t.get('l4')=='格局':notes.add('客餐厨一体化的LDK及其包含阳台的LDKB等扩展，均明确了客厅与餐厨的空间组织，可属于客厅格局；横厅/竖厅/边厅只是字典示例，不是封闭枚举，也不强制再给面宽数字。')
  if t.get('l2')=='总图规划' and t.get('l3')=='户数':notes.add('“整体只有/社区仅/共计N户(席)”均可明确项目总量；不必须逐字出现“全盘”或“总户数”。但首开/批次/在售N套不作总量。')
  if t.get('l2')=='产品价格' and t.get('l3') in ['精装单价','精装总价']:notes.add('同一片、同一房源明确精装交付且列备案均价/总价，可按该精装房源价格记录备案口径；不是推算纯装修费用。未明交付类型不得强归精装。')
 return '\n本次适用路径解释：\n'+'\n'.join(sorted(notes)) if notes else ''

def joint_review(doc,unit,tax,runner):
 labels=unit['labels'];ids={x['tag_id'] for x in labels}
 if not ids:return [],{'checks':[]}
 payload={'unit_text':unit['text'],'evidence_grid':base.atoms(unit),'taxonomy':base.compact_tax([t for t in tax if t['tag_id'] in ids]),'draft_labels':labels}
 schema=base.obj({'checks':base.arr(base.obj({'tag_id':{'type':'string','enum':sorted(ids)},'keep':{'type':'boolean'},
                  'actual_object':base.S,'attribute':base.S,'evidence_ids':base.arr({'type':'integer','minimum':1}),
                  'reason':{'type':'string','minLength':1,'maxLength':240}}))})
 previous=None;error=None
 for attempt in range(2):
  repair={**payload,'validation_error':error,'repair_instruction':'重新给出完整checks，每项reason仅一句不超过120字的证据结论。不要复述旧输出、不要反复推演，不以定义示例添加新门槛。'}
  answer=base.call(runner,doc,JOINT+definition_notes([t for t in tax if t['tag_id'] in ids]),payload if not attempt else repair,'专题一同片多标签对象复核' if not attempt else '专题一同片对象复核合同修复',schema=schema if attempt else None)
  try:
   checks=answer.get('checks');assert isinstance(checks,list),'Missing joint checks'
   got=[c.get('tag_id') for c in checks];assert len(got)==len(set(got)) and set(got)==ids,'Joint checks must cover exactly selected tags'
   kept=[]
   for c in checks:
    assert type(c.get('keep'))==bool and c.get('reason') and len(c['reason'])<=240,'Invalid joint verdict or long reasoning'
    if not c['keep']:continue
    assert not any(s in c['reason'] for s in ['不匹配','不符合','不满足','不应标','不予保留']),'Selected tag reason rejects itself'
    temp=copy.deepcopy(unit);temp['index']=1
    base.attach_grid([temp],{'units':[{'index':1,'labels':[{'tag_id':c['tag_id'],'reason':c['reason'],'evidence_ids':c.get('evidence_ids')}]}]},tax)
    definition=next(t for t in tax if t['tag_id']==c['tag_id'])
    veto=recall.proof_contract(definition,temp['labels'][0]['quote']) or recall.context_contract(definition,unit,temp['labels'][0])
    if veto:
     c['model_keep_before_contract']=True;c['keep']=False;c['reason']=veto;c['decision_method']='positive_evidence_contract'
    else:kept.extend(temp['labels'])
   return kept,answer
  except (AssertionError,KeyError,ValueError,TypeError) as e:previous=answer;error=str(e)
 raise ValueError('Joint review contract failed after bounded repair: '+str(error))
