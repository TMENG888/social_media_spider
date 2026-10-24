"""Bounded Qwen schema-only recovery on remaining failures; preserve accepted sources."""
import sys
import run500 as batch

class RepairRunner(batch.Runner):
    def call(self,system,payload,doc,phase,response_schema=None):
        answer,metrics=super().call(system,payload,doc,phase,response_schema=response_schema)
        if phase=='专题一摘要编号核验合同修复' and metrics['status']=='success':
            import summary_evidence
            try:
                summary_evidence.decode(payload['unit_text'],''.join(c['text'] for c in payload['claims']),payload['evidence_grid'],answer,payload['level']!='I0 无创新判断')
            except (ValueError,KeyError,TypeError):
                ids=[e['id'] for e in payload['evidence_grid']]
                claims=[c['id'] for c in payload['claims']]
                evidence={'type':'array','items':{'type':'integer','enum':ids}} if ids else {'type':'array','items':{'type':'integer'},'maxItems':0}
                checks=batch.pipeline.arr(batch.pipeline.obj({'claim_id':{'type':'integer','enum':claims},'supported':{'type':'boolean'},'evidence_ids':evidence,'reason':{'type':'string','minLength':1}}))
                checks.update(minItems=len(claims),maxItems=len(claims))
                schema=batch.pipeline.obj({'checks':checks,'innovation_supported':{'type':'boolean'},'innovation_issue':batch.pipeline.S})
                repaired,repair_metrics=super().call(system+'\n严格核验证据编号恢复：每个输入claim_id恰好一次，evidence_ids只能使用当前evidence_grid的id；无法支持的主张必须supported=false，不得捏造证据。保持原有独立证据核验语义，不为通过校验把不支持改成支持。',
                    {**payload,'invalid_draft':answer},doc,phase+'严格证据编号恢复',response_schema=schema)
                batch.save(batch.ROOT/'summary_evidence_recovery'/f'{metrics["request_key"]}.json',{'record_id':doc['record_id'],'invalid_draft':answer,'repair':repaired,'repair_status':repair_metrics['status']})
                return repaired,repair_metrics
            return answer,metrics
        if phase=='专题一字段独立生成' and metrics['status']=='success':
            expected=[u['index'] for u in payload['units']]
            valid=isinstance(answer,dict) and isinstance(answer.get('units'),list) and all(isinstance(u,dict) and type(u.get('index'))==int for u in answer['units'])
            if valid:valid=len(answer['units'])==len(expected) and {u.get('index') for u in answer['units']}==set(expected)
            if not valid:
                fields={k:batch.pipeline.S for k in ['reason','brand','entity','entity_evidence','project','city','practice','innovation_reason','identity_evidence']}
                fields.update(index={'type':'integer','enum':expected},deliver={'type':'boolean'},innovation={'type':'string','enum':batch.pipeline.INNOVATIONS},level={'type':'string','enum':batch.pipeline.LEVELS})
                units_schema=batch.pipeline.arr(batch.pipeline.obj(fields));units_schema.update(minItems=len(expected),maxItems=len(expected))
                schema=batch.pipeline.obj({'publisher_role':{'type':'string','enum':batch.pipeline.ROLES},'publisher_evidence':batch.pipeline.S,'units':units_schema})
                repaired,repair_metrics=super().call(system+'\n完整条目恢复：必须返回每个输入index恰好一次，不遗漏、不重复，不改变切片边界。所有身份、产品范围、摘要及创新判断仍只按给定原文和规则独立判断。',
                    {**payload,'invalid_draft':answer,'expected_indices':expected},doc,phase+'完整条目合同恢复',response_schema=schema)
                batch.save(batch.ROOT/'annotation_recovery'/f'{metrics["request_key"]}.json',{'record_id':doc['record_id'],'invalid_draft':answer,'repair':repaired,'repair_status':repair_metrics['status']})
                return repaired,repair_metrics
        if phase=='专题一局部切片合同修复' and metrics['status']=='success':
            parts=batch.pipeline.resolve_cuts({'text':payload['text']},answer)
            if parts[0]['anchor_audit'].get('model_quote') is None:
                text=payload['text']
                positions=list(range(len(text))) if len(text)<=4096 else [0]+[i for i in range(1,len(text)) if text[i-1] in '。！？；，\n']
                grid=[{'id':i,'anchor':text[pos:pos+16]} for i,pos in enumerate(positions)]
                schema=batch.pipeline.obj({'cuts':batch.pipeline.arr(batch.pipeline.obj({'anchor_id':{'type':'integer','minimum':0,'maximum':len(grid)-1},'theme':batch.pipeline.S}))})
                repaired,repair_metrics=super().call(system+'\n严格位置恢复：改为从原文定位网格选择anchor_id。必须明确选择第0个定位编号为首切点；所有编号按原文递增且不重复。网格仅定位，按独立语义主题切片，不能逐字或逐网格机械切片。不翻译或改写原文。只输出cuts数组，每项anchor_id和theme。',
                    {'text':text,'anchor_grid':grid,'invalid_draft':answer},doc,phase+'显式首切点编号恢复',response_schema=schema)
                batch.save(batch.ROOT/'anchor_recovery'/f'first_{metrics["request_key"]}.json',{'record_id':doc['record_id'],'invalid_draft':answer,'repair':repaired,'repair_status':repair_metrics['status']})
                if repair_metrics['status']!='success':return repaired,repair_metrics
                indices=[c['anchor_id'] for c in repaired['cuts']]
                assert indices and indices[0]==0 and indices==sorted(set(indices))
                cuts=[]
                for c in repaired['cuts']:
                    pos=positions[c['anchor_id']];quote=text[pos:pos+16]
                    cuts.append({'quote':quote,'occurrence':batch.pipeline.occurrences(text,quote).index(pos)+1,'theme':c['theme']})
                return {'cuts':cuts},repair_metrics
        if phase=='专题一当前切片摘要合同修复' and metrics['status']=='success':
            valid=isinstance(answer,dict) and type(answer.get('deliver'))==bool and answer.get('innovation') in batch.pipeline.INNOVATIONS and answer.get('level') in batch.pipeline.LEVELS
            force_product='verified_current_unit_labels' in payload
            if valid:valid=(not force_product or answer['deliver']) and (not answer['deliver'] or bool(str(answer.get('practice','')).strip()))
            if not valid:
                schema=batch.pipeline.obj({'deliver':({'type':'boolean','enum':[True]} if force_product else {'type':'boolean'}),'reason':{'type':'string'},'practice':{'type':'string'},
                    'innovation':{'type':'string','enum':batch.pipeline.INNOVATIONS},'level':{'type':'string','enum':batch.pipeline.LEVELS},'innovation_reason':{'type':'string'}})
                repaired,repair_metrics=super().call(system+'\n格式与一致性合同恢复：创新类型、创新等级严格使用给定枚举；有verified_current_unit_labels时遵守原force_product规则，deliver=true且给出非空的本片摘要；无此字段时独立决定范围。只依据本片原文，不创造其他选项或借别段事实。其他语义、数值与状态规则保持不变。',
                    {**payload,'invalid_draft':answer,'allowed_innovations':batch.pipeline.INNOVATIONS,'allowed_levels':batch.pipeline.LEVELS},doc,
                    phase+'严格枚举恢复',response_schema=schema)
                batch.save(batch.ROOT/'summary_recovery'/f'{metrics["request_key"]}.json',{'record_id':doc['record_id'],'invalid_draft':answer,'repair':repaired,'repair_status':repair_metrics['status']})
                if repair_metrics['status']=='success' and isinstance(repaired,dict) and repaired.get('deliver') is True and not str(repaired.get('practice','')).strip():
                    schema['properties']['practice']={'type':'string','minLength':1}
                    schema['properties']['deliver']={'type':'boolean','enum':[True]}
                    nonempty,nonempty_metrics=super().call(system+'\n非空摘要恢复：本片已判为产品信息，practice不得空白，须用一句话概括unit_text明确的产品做法、原数值和限定；不能借其他段内容，不得改变标签或为凑摘要新增事实。',
                        {**payload,'invalid_draft':repaired,'allowed_innovations':batch.pipeline.INNOVATIONS,'allowed_levels':batch.pipeline.LEVELS},doc,
                        phase+'非空摘要恢复',response_schema=schema)
                    batch.save(batch.ROOT/'summary_recovery'/f'nonempty_{metrics["request_key"]}.json',{'record_id':doc['record_id'],'invalid_draft':repaired,'repair':nonempty,'repair_status':nonempty_metrics['status']})
                    return nonempty,nonempty_metrics
                return repaired,repair_metrics
        if phase!='专题一身份编号合同修复' or metrics['status']!='success':return answer,metrics
        ids=[e['id'] for e in payload['evidence_grid']]
        fields=['brand','entity','city','publisher_role']
        valid=isinstance(answer,dict)
        if valid:
            valid=all(isinstance(answer.get(f),dict) and isinstance(answer[f].get('value'),str)
                and isinstance(answer[f].get('evidence_ids'),list)
                and all(type(i)==int and i in ids for i in answer[f]['evidence_ids']) for f in fields)
        if valid:return answer,metrics
        proof_schema={'type':'array','items':{'type':'integer','enum':ids}} if ids else {'type':'array','items':{'type':'integer'},'maxItems':0}
        props={f:batch.pipeline.obj({'value':{'type':'string'},'evidence_ids':proof_schema}) for f in fields}
        props['entity']['properties']['value']={'type':'string','enum':['',*payload['allowed_entities']]}
        props['publisher_role']['properties']['value']={'type':'string','enum':batch.pipeline.ROLES}
        props['same_project_reason']={'type':'string'}
        repaired,repair_metrics=super().call(system+'\n格式定位恢复：证据编号只能从当前evidence_grid的id中选择；不得用来源ID、段落序号、字数或臆造编号替代。证据不足的身份值留空且证据数组为空；发布者无证据为身份不明。仅修复输出合同，所有原语义和同盘证据规则保持不变。',
            {**payload,'invalid_draft':answer,'repair_error':'身份结构或引文编号不合法'},doc,
            phase+'严格编号恢复',response_schema=batch.pipeline.obj(props))
        batch.save(batch.ROOT/'identity_recovery'/f'{metrics["request_key"]}.json',{'record_id':doc['record_id'],'invalid_draft':answer,'repair':repaired,'repair_status':repair_metrics['status']})
        return repaired,repair_metrics

if __name__=='__main__':
    prior=batch.read(batch.ROOT/'status.json')
    assert prior['finished'] and not prior['auth_stopped'],'Only resume a finished, non-auth-failed pass'
    import recovery_scope_guard
    recovery_scope_guard.install(batch)
    batch.Runner=RepairRunner
    sys.argv=[str(batch.ROOT/'run500.py'),'--limit','500']
    try:batch.main()
    finally:
        execution=batch.read(batch.ROOT/'execution.json')
        execution.update(recovery_wrapper_path=__file__,recovery_wrapper_sha256=batch.sha(batch.Path(__file__)),scope_recovery_wrapper_sha256=batch.sha(batch.ROOT/'recovery_scope_guard.py'),recovery_policy='仅对失败来源恢复严格证据编号、首切点、摘要枚举和非空摘要、字段完整性；标签与不交付范围冲突时，由Qwen独立核实住宅自身归属，非住宅对象撤销无效标签，原候选及裁决留审计。不改冻结r49文件、生产入口或已成功来源结果。')
        batch.save(batch.ROOT/'execution.json',execution)
