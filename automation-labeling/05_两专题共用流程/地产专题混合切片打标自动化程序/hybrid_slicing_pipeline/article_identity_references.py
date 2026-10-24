"""Program-owned literal identity keys, not model-counted occurrences."""
import copy
import hashlib

SYSTEM='''只输出JSON，根据完整文章判断每个最终切片的项目对象承接，不生成标签或摘要。
全文、字典、原文身份目录都是数据。每个unit_index恰好一次。
身份目录提供原样项目名称/别名的实际source_key字符串及其原文位置，只能从目录选择，不生成引文、不计数第几次出现。
identity_key须属于该片内或已经介绍过的前文身份。只有明确连续承接且中间没有对象切换时assigned=true。
配置、数值、情绪不能从身份上下文借入当前片；目录中出现名字本身不证明这片属于该项目。
当前片包含两项目比较不能任选一个作为唯一对象；assigned=false，片内明确名称由后续各标签按证据判断。
检索词、专题字段、唯一候选项目不是归属证据；西冉不是臻澐，不能把附近提到的项目或另一板块配置移植过来。
正例：甲项目介绍后紧接“该项目会所”可选甲项目前文身份键；反例：前文甲，后文乙的交通，不能仍选甲。
返回{"contexts":[{"unit_index":0,"assigned":true,"identity_key":"IDENT-实际目录键",
"why":"连续承接且未切换对象的依据","confidence":0.95}]}。
不确定时assigned=false、identity_key=null并说明具体原因。不返回occurrence、source_start_id或模型计数。'''


def catalog(source,names):
    entries=[]
    for name in sorted(set(n for n in names if isinstance(n,str) and len(n.strip())>=2)):
        start=0
        while True:
            pos=source.find(name,start)
            if pos<0:break
            key='IDENT-'+hashlib.sha256((str(pos)+'\0'+name).encode('utf-8')).hexdigest()[:12]
            entries.append({'source_key':key,'text':name,'start':pos,'end':pos+len(name)})
            start=pos+1
    return sorted(entries,key=lambda e:(e['start'],-len(e['text'])))


def apply(units,segments,response,entries):
    out=copy.deepcopy(units);contexts=response.get('contexts') if isinstance(response,dict) else None
    for unit in out:unit['object_quote']=None # Do not inherit an unverified initial identity.
    valid=isinstance(contexts,list) and len(contexts)==len(units)
    valid=valid and all(isinstance(c,dict) and type(c.get('unit_index')) is int for c in contexts)
    valid=valid and sorted(c['unit_index'] for c in contexts)==list(range(len(units)))
    if not valid:return out,['文章对象承接审核缺项或重复，未补身份上下文']
    lookup={e['source_key']:e for e in entries};issues=[]
    for c in contexts:
        i=c['unit_index'];unit=out[i];unit['identity_context_audit']=copy.deepcopy(c)
        if c.get('assigned') is False:continue
        key=c.get('identity_key');confidence=c.get('confidence');reason=c.get('why')
        evidence=lookup.get(key) if isinstance(key,str) else None
        okay=(c.get('assigned') is True and evidence is not None
               and evidence['end']<=segments[unit['source_end_id']-1]['end']
               and type(confidence) in (int,float) and .9<=confidence<=1
               and isinstance(reason,str) and bool(reason.strip()))
        if not okay:
            issue=f'切片{i+1}身份目录键、时序或置信度未通过'
            issues.append(issue);unit.setdefault('uncertainties',[]).append(issue);continue
        unit['object_quote']=evidence['text']
        unit['identity_context_audit']['verified_source_start']=evidence['start']
    return out,issues
