"""Claim-by-claim local summary review using source-address selections.

No gold answers, source IDs, topic examples or reference-workbook access.
The program partitions the summary; the model cannot omit/rewrite claims.
"""
import re
from difflib import SequenceMatcher
VERSION='t1-summary-evidence-r3-object-record-blocks'
SYSTEM='''逐条核验住宅产品摘要，只使用unit_text，不看标题、全文其他段或常识。
claims由程序分出，必须对每个claim_id恰好返回一项checks，不改写、不跳过。逐项核对对象、数值与单位、品牌或风格专名、状态、条件、确定程度。
evidence_grid是本片连续原文定位编号，不是另一个来源。supported=true必须给出支持这项主张的evidence_ids，选择最短充分连续范围；程序取原文，不重写引文。没有支持就false，不因摘要读起来合理而批准。
数字相同但擅补㎡、米、层等单位仍是无据事实。ASR的模糊品牌/风格/设备词不能凭常识纠为确定名称。宣传生活感受不能专业化为原文未说的热工、隔声、节能、健康等技术性能。
样板/拟建/宣传/推测不能写成交付实绩；原文有冲突的时间、朝向、明暗卫等不能单取一说当确定结论；保留未公示、以合同为准等实质限定。现场检查建议不能当已观察到的配置表现。
自然表达和同义转述允许，省略非核心信息不直接判错；不得要求摘要逐字照抄或把来源真实性核实当摘要忠实性。原文明确“精装”“顶配会所”可转述为“来源称采用精装/配会所”，不要求来源再提供交付证明；只是不能把来源的营销形容词专业化为新技术性能。I1只表示来源自称首创不等于已证实；I2/I3要本片迭代/比较证据；普通高端修辞只支持I0。
证据表中record_object标明的是原文连写户型表的记录边界。一个面积编号之后的房厅卫、阳台、套房等描述属于该记录，直到下一个面积编号开始；不能看见下一记录编号就反过来给上一条配置换对象。claims中的object_hint仅是摘要声称的对象，不是已证实归属；须核对同编号原文记录。即使同片共现某空间，也不表示雕塑、设施或数值都属于它，证据须说明该属性与此对象的实际关系。
JSON {"checks":[{"claim_id":1,"supported":true,"evidence_ids":[1],"reason":"一句话核验结论"}],"innovation_supported":true,"innovation_issue":""}。unsupported必须说明实际不受支持的内容。不得核验标签或增删标签。'''

SCHEMA={'type':'object','properties':{
 'checks':{'type':'array','items':{'type':'object','properties':{
  'claim_id':{'type':'integer'},'supported':{'type':'boolean'},
  'evidence_ids':{'type':'array','items':{'type':'integer'}},'reason':{'type':'string','maxLength':160}},
  'required':['claim_id','supported','evidence_ids','reason'],'additionalProperties':False}},
 'innovation_supported':{'type':'boolean'},'innovation_issue':{'type':'string','maxLength':160}},
 'required':['checks','innovation_supported','innovation_issue'],'additionalProperties':False}
AREA=re.compile(r'(?<![\d.])\d{2,4}(?:\s*[-–—‑/]\s*\d{2,4})?\s*(?:㎡|平方米|平米)')
SPACES=r'地下车库|地下大堂|电梯厅|外立面|主卧|次卧|客厅|餐厅|厨房|卫生间|阳台|露台|庭院|园林|景观|会所|大门|门楼|围墙|地库'
def canonical_space(s):return {'园林':'景观','门楼':'大门','地库':'地下车库'}.get(s,s)

FACILITY_TERMS={
 '篮球':['篮球','篮场'], '羽毛球':['羽毛球','羽球'],
 '网球':['网球'], '乒乓球':['乒乓球','乒乓'],
 '足球':['足球'], '排球':['排球'], '壁球':['壁球'],
}
def unsupported_facility_expansions(text,practice):
    """Specific facility types may not be invented from a generic/ASR label.

    A negative ontology guard, not an automatic correction dictionary. It
    never interprets an unclear term or substitutes a guessed facility.
    """
    return ['摘要新增原文未明确的设施类型：'+term+'；不将泛称或含混缩写展开为确定配置。'
            for term,forms in FACILITY_TERMS.items()
            if term in practice and not any(form in text for form in forms)]

def colisted_container_conflicts(text,practice):
    """Do not turn a completed status clause plus a list into containment."""
    issues=[]
    for m in re.finditer('('+SPACES+r')[^。；]{0,18}?(?:包含|包括|内设|内有)([^。；]+)',practice):
        owner=m.group(1)
        status=re.search(re.escape(owner)+r'[^，,。；]{0,16}(?:投入运营|开放使用|已开放|已运营)[，,]',text)
        explicit=re.search(re.escape(owner)+r'(?:内|里|中|[：:]|[^，,。；]{0,6}(?:设有|配置|包含|包括|配备|拥有))',text)
        if status and not explicit:
            issues.append('原文将'+owner+'运营状态和其他配套并列，未证明全部配套都在'+owner+'内部；摘要须保持并列，不新增包含关系。')
    return issues

def personal_proposal_conflicts(text,practice):
    """Detect copied proposal attributes losing their source modality.

    This is a negative-only contradiction check; it never writes a summary,
    creates facts, repairs ASR words, or changes a label decision.
    """
    issues=[]
    for clause in re.finditer(r'(?:可以作为|(?:后期|如果)[^，。；,;]{0,14}(?:改成|改为|做成)|可(?:以)?改(?:成|为))([^，。；,;]+)',text):
        proposed=clause.group(1)
        for c in re.split(r'[，。；,;]',practice):
            if re.search(r'可以|可作|可改|建议|拟|后期|可能|方案|条件|待|原文|计划|改造',c):continue
            match=SequenceMatcher(None,proposed,c,autojunk=False).find_longest_match()
            anchor=proposed[match.a:match.a+match.size]
            if match.size<3 or re.fullmatch(SPACES+'|的设计|的空间|的配置|一个',anchor):continue
            # An independently stated existing attribute elsewhere is not
            # contradicted merely because the same attribute is also proposed.
            outside=text[:clause.start()]+text[clause.end():]
            if anchor in outside:continue
            issues.append('“'+anchor+'”仅在原文个人可能/后期改造方案中出现，摘要不能去掉该限定写成已有配置。')
    return issues
def explicit_owner_conflicts(text,practice):
    """Veto explicit summary ownership contrary to the local spatial order.

    This only detects contradictions, not a general syntactic entailment proof.
    Ambiguous claims are still assessed by the separate semantic reviewer.
    """
    issues=[]
    for claim in re.finditer('('+SPACES+r')(?:内|中|内部)?(?:拥有|设有|配置|配备|内设|设置|包含|采用)([^；。]+)',practice):
        owner=canonical_space(claim.group(1));payload=claim.group(2)
        # Find a substantive untouched attribute fragment, not a source ID,
        # label answer, handcrafted case phrase or corrected ASR brand.
        match=SequenceMatcher(None,payload,text,autojunk=False).find_longest_match()
        if match.size<3:continue
        anchor=payload[match.a:match.a+match.size];hits=[m.start() for m in re.finditer(re.escape(anchor),text)]
        nearby=[]
        for pos in hits:
            locations=list(re.finditer(SPACES,text[max(0,pos-180):pos]))
            if locations:nearby.append(canonical_space(locations[-1].group()))
        if nearby and owner not in nearby:
            issues.append('摘要将“'+anchor+'”明确归于'+claim.group(1)+'，但原文该属性附近的空间为'+ '/'.join(sorted(set(nearby)))+'；不能跨空间移植，无法确认时只保留项目层面的做法。')
    return issues
def object_key(value):return re.sub(r'\s+','',value).translate(str.maketrans('–—‑','---'))
def evidence_blocks(text):
    headers=[m for m in AREA.finditer(text) if re.match(r'[^，。；\n]{0,16}[\d一二三四五六七八九]+[房室居]',text[m.end():m.end()+30])]
    # Only explicit repeated floorplan records are segmented by area headers.
    # Other area figures (landscape, pools, bedrooms) are not plan objects.
    if len(headers)>=2:
        cuts=[0]+[m.start() for m in headers[1:]]+[len(text)]
        return [{'id':i+1,'start':a,'end':b,'text':text[a:b],
                 'record_object':object_key(headers[i].group())} for i,(a,b) in enumerate(zip(cuts,cuts[1:]))]
    spans=[]
    for m in re.finditer(r'[^。；\n]+[。；\n]*|[。；\n]+',text):
        for start in range(m.start(),m.end(),320):
            end=min(start+320,m.end());spans.append({'id':len(spans)+1,'start':start,'end':end,'text':text[start:end]})
    return spans

def claims(practice):
    out=[];context=''
    for i,m in enumerate(re.finditer(r'[^，。；！？!?;\n]+[，。；！？!?;\n]*',practice)):
        names=list(AREA.finditer(m.group()))
        if names:context=object_key(names[-1].group())
        out.append({'id':i+1,'text':m.group(),'object_hint':context})
    return out

def decode(text,practice,grid,answer,check_innovation=True):
    parts=claims(practice);expected={c['id'] for c in parts}
    checks=answer.get('checks')
    if not isinstance(checks,list) or len(checks)!=len(parts) or {c.get('claim_id') for c in checks}!=expected:
        raise ValueError('Summary checks must cover each program-generated claim exactly once')
    by={a['id']:a for a in grid};ct={c['id']:c for c in parts};issues=[];proofs=[]
    for c in checks:
        if type(c.get('supported'))!=bool or not c.get('reason') or not isinstance(c.get('evidence_ids'),list):
            raise ValueError('Invalid summary check fields')
        ids=c['evidence_ids']
        if any(type(i)!=int or i not in by for i in ids):raise ValueError('Unknown summary evidence address')
        if c['supported'] and not ids:raise ValueError('Approved summary claim requires local evidence IDs')
        quote=text[by[min(ids)]['start']:by[max(ids)]['end']] if ids else ''
        hint=ct[c['claim_id']]['object_hint'];available={a.get('record_object') for a in grid if a.get('record_object')}
        if c['supported'] and hint in available:
            chosen={by[i].get('record_object') for i in ids}
            if chosen!={hint}:
                c={**c,'supported':False,'model_supported_before_contract':True,'reason':'摘要声称的户型与所选原文记录不一致；不从相邻户型借用配置。','decision_method':'floorplan_object_record_guard'}
        proofs.append({**c,'claim':ct[c['claim_id']]['text'],'object_hint':hint,'source_quote':quote})
        if not c['supported']:issues.append(ct[c['claim_id']]['text']+'：'+c['reason'])
    if type(answer.get('innovation_supported'))!=bool:raise ValueError('Missing innovation verdict')
    if check_innovation and not answer['innovation_supported']:
        if not answer.get('innovation_issue'):raise ValueError('Missing innovation issue')
        issues.append('创新：'+answer['innovation_issue'])
    return {'supported':not issues,'issues':issues,'claims':proofs,'innovation_supported':answer['innovation_supported'],
            'innovation_check_required':check_innovation,'review_engine':VERSION}

def review(doc,u,runner,call,grid):
    grid=evidence_blocks(u['text'])
    payload={'unit_text':u['text'],'claims':claims(u['practice']),'evidence_grid':grid,
             'innovation':u['innovation'],'level':u['level'],'innovation_reason':u['innovation_reason']}
    answer=call(runner,doc,SYSTEM,payload,'专题一摘要逐主张编号核验',SCHEMA)
    # I0 is an explicit absence of an innovation assertion, so "no innovation
    # evidence" cannot contradict it. Only positive levels need entailment.
    check_innovation=u['level']!='I0 无创新判断'
    try:return decode(u['text'],u['practice'],grid,answer,check_innovation)
    except (ValueError,KeyError,TypeError) as e:
        answer=call(runner,doc,SYSTEM,{**payload,'previous':answer,'validation_error':str(e)},'专题一摘要编号核验合同修复',SCHEMA)
        return decode(u['text'],u['practice'],grid,answer,check_innovation)
