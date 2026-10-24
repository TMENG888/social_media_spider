"""Full-source model review with small boundary batches and scoped recovery.

No keyword/length rule selects final slice boundaries. All valid decisions
must cover the article and pass the existing lossless merge contract.
"""
import copy
from concurrent.futures import ThreadPoolExecutor
import continuity_edge_references as refs
import continuity_edge_scope_recovery as scope


def review(doc,plan,excerpts,runner,batch_size=5):
    if doc.get('kind')!='文章' or len(excerpts)<2:return plan,[],[],[]
    if not 1<=batch_size<=5:raise ValueError('Boundary batch size must be 1..5')
    entries=refs.model_catalog(excerpts)
    for i,entry in enumerate(entries):
        entry['left_relevant']=plan['units'][i].get('relevant')
        entry['right_relevant']=plan['units'][i+1].get('relevant')
    valid={};calls=[];audit=[]
    instruction=refs.SYSTEM+'''\n只判断本次少量目录中的真实左右原文，不按全文的段落序号对应键。
左右相关性不同不合并；也不能把户型定位结论与独立层高维度仅因同项目全部吞并。
why准确描述本键的left_text和right_text，不描述下一个边界。不重复上次的错位解释。
仍拿到source_text完整文章，前后文只用于理解对象和承接。'''
    missing=list(entries)
    for attempt in range(2):
        batches=[missing[i:i+batch_size] for i in range(0,len(missing),batch_size)]
        def check_batch(batch):
            payload={'source_text':doc['text'],'topic':doc['topic'],'edge_catalog':batch}
            if attempt:payload['repair_issues']='只补本目录中未通过的边界，不覆盖其他已有效决定；核左右实际原文及相关性'
            raw,m=runner.call(instruction,payload,doc,
                '全文上下文少量边界原文键审核-v11.27' if not attempt else '边界缺项及范围冲突定向恢复-v11.27')
            accepted,unresolved,protocol_issues=refs.decisions(raw if m['status']=='success' else None,batch,doc['topic'])
            return accepted,m,{'attempt':attempt,'requested_keys':[e['edge_key'] for e in batch],
                'response':raw,'unresolved_keys':unresolved,'protocol_issues':protocol_issues}
        with ThreadPoolExecutor(max_workers=10) as pool:outputs=list(pool.map(check_batch,batches))
        for accepted,m,record in outputs:
            valid.update(accepted);calls.append(m);audit.append(record)
        valid,scope_issues=scope.filter_valid(plan,entries,valid)
        if scope_issues:audit.append({'attempt':attempt,'scope_issues':scope_issues})
        missing=[e for e in entries if e['edge_key'] not in valid]
        if not missing:break
    # Unresolved boundaries remain physically intact, but are NOT verified
    # keep decisions. They must not cancel independent, valid merges elsewhere.
    unresolved={e['edge_key'] for e in missing}
    pending=copy.deepcopy(plan)
    if unresolved:
        affected=set()
        for i,e in enumerate(entries):
            if e['edge_key'] in unresolved:affected.update((i,i+1))
        for i in affected:
            pending['units'][i].setdefault('uncertainties',[]).append(
                '相邻边界未完成语义核验：保留原边界待人工审核；其他已核实独立合并不受影响')
        audit.append({'verification_complete':False,'unresolved_keys':sorted(unresolved),
                      'policy':'未核实边界原样保留，不视为模型确认keep'})
    else:audit.append({'verification_complete':True,'unresolved_keys':[]})
    response={'edges':[valid.get(e['edge_key'],{
        'edge_key':e['edge_key'],'decision':'keep','confidence':1.0,
        'why':'程序保留未核实原边界，仅用于无损变换；不是模型语义验收'}) for e in entries]}
    merged,issues=refs.apply(pending,response,doc['topic'],excerpts)
    if not issues:merged['source_bound_continuity_review_audit']=copy.deepcopy(audit)
    return merged,audit,calls,issues
