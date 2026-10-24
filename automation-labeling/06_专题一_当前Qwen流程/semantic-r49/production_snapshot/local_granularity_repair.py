"""Bounded model-selected repairs, with full article context; no rule splitter."""
import copy
import re
from source_quote_alignment import quote_spans

SYSTEM='''只返回JSON。你收到完整source_text及先前未落实拆分的repair_targets。全文用于对象承接，不能照抄旧边界。
对每个目标独立判断：若只有一个具体主题，action=keep并解释；若含多个独立主题，action=split并返回真正不同的片头。
同一户型的连续细节、同一会所设施、同一施工方案保持整体。规划指标、交通、教育、医疗、商业、生态、产业是不同主题，不能因为“周边配套”栏目合并。
只修改目标区间，不能遗漏或借入目标外文本；程序按起点回填完整原文。不按字数或标签数切分。
start_quote只取目标中片头15至40字，不输出整片，不改写。start_occurrence为该引文在目标区间中的第几次，不是切片序号；唯一引文为1。
首片从目标区间开头取引文，split至少两个不同起点。每个目标恰好返回一次，不生成标签和摘要。
只输出{"repairs":[{"unit_index":0,"action":"keep","why":"一个具体主题","units":[]},
{"unit_index":1,"action":"split","why":"多个独立主题","units":[{"start_quote":"目标原文实际片头","start_occurrence":1,"scope_reason":"具体对象及主题","relevant":true},
{"start_quote":"下个主题实际片头","start_occurrence":1,"scope_reason":"另一个具体主题","relevant":true}]}]}。
why只写简短最终理由，不输出思考过程，不能一边说split一边保持一个起点。'''


def apply(plan,response,segments,required_indices):
    if not isinstance(response,dict) or not isinstance(response.get('repairs'),list):
        return plan,segments,['局部粒度恢复缺少repairs']
    repairs=response['repairs']
    if any(not isinstance(x,dict) or type(x.get('unit_index')) is not int for x in repairs):
        return plan,segments,['局部粒度恢复索引非法']
    if sorted(x['unit_index'] for x in repairs)!=sorted(required_indices):
        return plan,segments,['局部粒度恢复目标重复或缺失']
    mapped={x['unit_index']:x for x in repairs};out=copy.deepcopy(plan)
    out['units']=[];new_segments=[]
    for i,old in enumerate(plan['units']):
        selected=segments[old['source_start_id']-1:old['source_end_id']]
        text=''.join(x['text'] for x in selected);base=selected[0]['start']
        repair=mapped.get(i);starts=[0];parts=[{}]
        if repair:
            if repair.get('action') not in {'keep','split'} or not str(repair.get('why') or '').strip():
                return plan,segments,['局部粒度恢复决定或理由非法']
            if repair['action']=='split':
                parts=repair.get('units')
                if not isinstance(parts,list) or len(parts)<2:
                    return plan,segments,['声称局部拆分但没有多个起点']
                starts=[]
                for part_number,part in enumerate(parts):
                    if not isinstance(part,dict):return plan,segments,['局部片头不是对象']
                    if part.get('from_target_start') is True:
                        if part_number!=0:return plan,segments,['仅首片可引用已存在的目标起点']
                        if not str(part.get('scope_reason') or '').strip() or type(part.get('relevant')) is not bool:
                            return plan,segments,['局部切片主题或相关性缺失']
                        starts.append(0)
                        continue
                    quote=part.get('start_quote')
                    spans=quote_spans(text,quote)
                    # start_quote is an anchor, not a full slice. An overlong
                    # model anchor can include the next original interval; use
                    # its grounded beginning only, never borrow the extra text.
                    if not spans and isinstance(quote,str) and len(quote)>40:
                        spans=quote_spans(text,quote[:40])
                    occurrence=part.get('start_occurrence',1)
                    if not spans or type(occurrence) is not int or not 1<=occurrence<=len(spans):
                        return plan,segments,['局部片头不可定位或出现序号非法']
                    pos=spans[occurrence-1][0]
                    if part_number==0 and pos and not re.fullmatch(r'\s*\d+[、.．]\s*[\u4e00-\u9fff]{1,12}\s*',text[:pos]):
                        return plan,segments,['首个局部起点遗漏非标题正文，不能自动吞并未解释事实']
                    # The first target boundary already exists. Preserve its
                    # prefix/header rather than dropping it when the model
                    # starts after a heading; no new internal cut is inferred.
                    starts.append(0 if part_number==0 else pos)
                    if not str(part.get('scope_reason') or '').strip() or type(part.get('relevant')) is not bool:
                        return plan,segments,['局部切片主题或相关性缺失']
                if starts[0]!=0 or starts!=sorted(set(starts)):
                    return plan,segments,['局部边界漏开头、重复或逆序']
        for j,start in enumerate(starts):
            end=starts[j+1] if j+1<len(starts) else len(text)
            unit=copy.deepcopy(old);part=parts[j];number=len(new_segments)+1
            unit.update(source_start_id=number,source_end_id=number,start_quote=text[start:min(end,start+40)])
            if repair and repair['action']=='split':
                unit.update(scope_reason=part['scope_reason'],relevant=part['relevant'],labels=[],summary=None,practice=None)
                score=part.get('boundary_confidence')
                unit.setdefault('confidence',{})['boundary']=score if type(score) in (int,float) and 0<=score<=1 else None
            unit.pop('_adjacent_semantic_merge',None)
            new_segments.append({'id':number,'start':base+start,'end':base+end,'text':text[start:end]})
            out['units'].append(unit)
    if ''.join(s['text'] for s in segments)!=''.join(s['text'] for s in new_segments):
        return plan,segments,['局部恢复改变或遗漏原文']
    out['local_granularity_audit']=copy.deepcopy(response)
    return out,new_segments,[]
