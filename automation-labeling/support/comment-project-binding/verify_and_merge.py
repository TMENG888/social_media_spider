"""Independently replay formal routing proofs and merge into a versioned cohort.

The base 587 snapshot and formal historical label calls stay immutable. A source
outside the four projects stays archived but does not count toward 1000 valid.
"""
import copy, html, json, sys, time
from collections import Counter
from pathlib import Path
sys.dont_write_bytecode=True
import project_priority as q
from run_pilot import PILOT
from structured_response_validation_v58 import issues

def check_ref(ref):
    assert q.sha(ref['file'])==ref['sha256'],'proof changed'
    return q.p.read(ref['file'])

def verify_stage(ref):
    stage=check_ref(ref);raw=stage['response']
    assert not issues(raw,stage['schema'])
    assert stage['input_sha256']==q.digest(stage['payload'])
    formal=[check_ref(x) for x in stage['formal_calls']]
    assert all(x['metrics']['status']=='success' for x in formal)
    assert formal[-1]['response']==stage.get('original_response',raw)
    if stage['phase'].startswith('A-'):
        payload=stage['payload']
        assert set(payload)=={'comment_text','known_projects','facts'}
        for f in payload['facts']:
            assert set(f)<= {'fact_id','tag_id','evidence','tag_name','tag_definition'}
        assert not q.validate_bindings(raw,[f['fact_id'] for f in payload['facts']],{'comment_text':q.comment_body(payload['comment_text'])})
    elif stage['phase'].startswith('P-'):
        assert not q.validate_projects(raw['projects'],stage['payload']['parent_fields'])
    elif stage['phase'].startswith('B-'):
        payload=stage['payload'];fields=dict(payload['parent_fields'],comment_text=q.comment_body(payload['comment_text']))
        assert not q.validate_bindings(raw,[f['fact_id'] for f in payload['requested_facts']],fields,True)
    return stage

def core_label(l):
    # Duplicate cross-project copies can have different verbal justifications;
    # their immutable original copies remain in the bound base inventory.
    return {k:l.get('object_previous',l[k]) if k=='object' else l[k] for k in ('tag_id','object','attribute_keys','context_keys')}

def original_object_label(l,pid):
    value=copy.deepcopy(l)
    if 'project_object_field_repair' in value:
        assert value['project_object_field_repair']['actor']=='program'
        assert value['object']==q.PM[pid]['name']
        assert value['object_previous'] in {name for project in q.PROJECTS for name in [project['name'],*project['aliases']]}
        value['object']=value.pop('object_previous')
        value.pop('project_object_field_repair')
    return value

def verify(source,overlay,revised):
    assert q.digest(source)==overlay['source_digest']
    assert source['document']==revised['document'] and source['units']==revised['units']
    assert source['publisher']==revised['publisher'] and source['score']==revised['score']
    assert overlay['facts']==q.facts(source)
    stages=[verify_stage(x) for x in overlay['formal_stage_proofs']]
    a=next(s for s in stages if s['phase'].startswith('A-'))
    bindings={x['fact_id']:dict(copy.deepcopy(x),method='comment_explicit' if x['decision']=='explicit' else 'unresolved') for x in a['response']['bindings']}
    # V1 had no developer guard; only V2 overlays use that declared correction.
    if overlay['version'].endswith(('v2','v3','v4','v5')):
        # Earlier revisions only demoted developer-only mentions. Preserve
        # their declared transformation when replaying immutable old proofs.
        if not overlay['version'].endswith(('v4','v5')):
            families={'P01':('华润',('臻','澐','云雅苑')),'C01':('建发',('海晏','海宴')),
                'C02':('中海',('安澜','安和','圆明')),'C05':('保利',('熙瑞','西瑞','瑞璟','半壁店'))}
            events=[]
            for binding in bindings.values():
                for project in binding['projects']:
                    if project['id'] not in families:continue
                    brand,tokens=families[project['id']];body=q.comment_body(source['document']['text'])
                    if brand in body and not any(token in body for token in tokens):
                        event={'fact_id':binding['fact_id'],'model_decision_preserved':copy.deepcopy(binding),
                               'reason':'评论仅有开发商品牌，无法隔离父文唯一推出该具体楼盘；改入父文消歧。'}
                        events.append(event)
                        binding.update(decision='unresolved',projects=[],method='unresolved',reason=event['reason']);break
        else:
            events=q.brand_guard(list(bindings.values()),source['document']['text'])
        assert events==overlay['identity_guard_events']
    for b in bindings.values():
        for x in b['projects']:x['evidence_field']='comment_text'
    unresolved=[b for b in bindings.values() if b['decision']=='unresolved']
    if unresolved:
        parent=next(s for s in stages if s['phase'].startswith('P-'))['response']
        assert parent==overlay['parent']
        if len(parent['projects'])==1:
            for b in unresolved:
                b.update(decision='context_resolved',projects=copy.deepcopy(parent['projects']),method='unique_parent_inherited',
                    reason='评论自身无明确具体楼盘，按用户规则继承父文章唯一主讲项目；父文仅用于身份归属。')
        else:
            ctx=next(s for s in stages if s['phase'].startswith('B-'))
            for b in ctx['response']['bindings']:bindings[b['fact_id']]=dict(copy.deepcopy(b),method='parent_context_resolved' if b['projects'] else 'ambiguous')
    assert list(bindings.values())==overlay['bindings'],'routing must replay from formal model decisions'
    expected=q.apply_overlay(source,overlay)
    for uid,o in revised['outcomes'].items():
        assert o['facts']==source['outcomes'][uid]['facts']
        actual_views={v['project_id']:v for v in o['views']}
        assert set(actual_views)=={v['project_id'] for v in expected['outcomes'][uid]['views']}
        for v in expected['outcomes'][uid]['views']:
            actual=actual_views[v['project_id']]
            assert [original_object_label(label,v['project_id']) for label in actual['labels']]==v['labels'],'tags cannot be added/dropped during project-only routing'
            if v.get('summary_project_repair_required'):
                stage=verify_stage(actual['summary_project_repair_proof'])
                chosen=next(x for x in stage['response']['views'] if x['project_id']==v['project_id'])
                assert all(actual[k]==chosen[k] for k in ('summary','expressions','emotions'))
            else:
                assert all(actual[k]==v[k] for k in ('summary','expressions','emotions'))
    assert revised['project_attribution_parked_labels']==expected['project_attribution_parked_labels']
    old=set(q.digest(core_label(l)) for o in source['outcomes'].values() for v in o['views'] for l in v['labels'])
    new=set(q.digest(core_label(l)) for o in revised['outcomes'].values() for v in o['views'] for l in v['labels'])
    new|={q.digest(core_label(x['label'])) for x in revised['project_attribution_parked_labels']}
    assert old==new,'all original label contents must remain active or parked'
    return {'record_id':source['record_id'],'passed':True,'stage_a_parent_isolation':True,
        'source_units_and_tag_semantics_preserved':True,'all_routes_formal_response_replayed':True}

def cost():
    total=Counter();unknown=0;files=0
    for folder in ('calls','call_attempt_history'):
        for f in (q.OUT/folder).glob('*.json'):
            r=q.p.read(f);m=r['metrics'];files+=1
            # Each file is one formal invocation, histories retain billed predecessors.
            for k in ('prompt_tokens','cached_input_tokens','completion_tokens','total_tokens','estimated_yuan'):
                if isinstance(m.get(k),(int,float)):total[k]+=m[k]
            unknown+=m.get('unknown_attempt_usage',0)
    return {'formal_ledger_records':files,**dict(total),'attempts_with_unknown_usage':unknown,
        'unknown_usage_not_zero':True,'http_diagnostics_not_added_again':True,
        'estimate_not_invoice':True,'not_including_historical_587_generation_cost':True}

def main():
    base=q.p.read(q.BASE);before=q.sha(q.BASE);by={s['record_id']:s for s in base['sources']}
    status=q.p.read(q.WORK/'run_status.json');assert not status['failures'] and status['completed']==10
    events={x['record_id']:x for x in status['events']};updated={};rows=[];verification=[];changed=0
    for rid,stratum in PILOT:
        event=events[rid];overlay=check_ref(event['overlay']);revised=check_ref(event['revised_source']);source=by[rid]
        verification.append(verify(source,overlay,revised));updated[rid]=revised
        changed_fact=False;details=[]
        routes={x['fact_id']:x for x in overlay['bindings']}
        for f in overlay['facts']:
            r=routes[f['fact_id']];old=set(x['old_project_id'] for x in f['refs']);new=set(x['id'] for x in r['projects'])
            if old!=new:changed_fact=True
            t=q.TM[f['tag_id']]
            details.append({'fact_id':f['fact_id'],'tag_id':f['tag_id'],'标签名':t['emphasis'],
                '修改前项目':[q.PM[x]['name'] for x in sorted(old)],
                '修改后项目':[x['name'] for x in r['projects']],'归属方式':r['method'],'理由':r['reason'],
                '引文':[x['quote'] for x in r['projects']]})
        changed+=changed_fact
        rows.append({'record_id':rid,'抽样类型':stratum,'评论原文':source['document']['text'],
            '父文标题':source['document']['parent'].get('文章标题',''),'归属变化':changed_fact,
            '状态':revised['state'],'标签对照':details,'正式证据':overlay['formal_stage_proofs']})
    revised_all=[updated.get(x['record_id'],copy.deepcopy(x)) for x in base['sources']]
    accepted=[s for s in revised_all if s['state']=='accepted'];excluded=[s for s in revised_all if s['state']!='accepted']
    counts=dict(Counter(s['kind'] for s in accepted))
    # Verify all 577 records outside the pilot are byte-for-value unchanged.
    assert all(s==by[s['record_id']] for s in revised_all if s['record_id'] not in updated)
    assert q.sha(q.BASE)==before
    meta={'version':q.VERSION,'created_at':time.time(),'base_inventory':q.reference(q.BASE),
        'base_source_total':587,'reviewed_comments':10,'unreviewed_comments':466,'unchanged_articles':111,
        'changed_source_project_assignments':changed,'outside_or_unresolved_sources':len(excluded),
        'effective_deduplicated_sources':len(accepted),'source_counts':counts,'target_gap':1000-len(accepted),
        'not_final_delivery':True,'all_1000_accepted':False,'pilot_semantic_review':'Codex evidence review, not independent human gold standard',
        'original_inventory_unchanged':True,'pilot_only_not_full_476_review':True}
    merged=meta|{'sources':accepted,'excluded_after_project_review':excluded,'prior_inventory_metadata':{k:v for k,v in base.items() if k!='sources'}}
    file=q.OUT/'587条库存_10条项目复核修正版.json';q.save(file,merged)
    q.save(q.OUT/'10条评论_项目归属前后对照.json',{'summary':meta,'sources':rows})
    q.save(q.OUT/'pilot_verification.json',meta|{'passed_all_structural_and_provenance_checks':True,'checks':verification,'cost':cost(),
        'semantic_review_notes':[
            '安澜兵营布局：去掉臻澐错误视图，仅归安澜。',
            '海晏天珺：父文标签明确保利海晏天珺，不是建发海晏。',
            '海晏府：父文明确深圳招商海晏府，不是北京建发海晏。',
            '瑜海澐颂：评论明确指名四项目外，不能沿用源文章任一四项目。',
            '混合长评论：洋房、阳台、学区均指子回复的熙瑞；首轮缺少标签含义导致错配，已用同一Qwen定向修复这3项。',
            '建发减配：仅品牌不能单独锁定具体楼盘，加入品牌保护，父文视频实际名建法海燕可解释ASR变体，继承建发海晏。',
            '这俩得房率：结合父文主讲华润臻澐与建发海晏，保留双项目而非任选一盘。']})
    q.save(q.WORK/'current_revision.json',{'inventory':q.reference(file),'pilot_verified':True,'only_10_comments_reviewed':True,
        'source_inventory_base':q.reference(q.BASE),'policy_file':q.reference(q.__file__)})
    esc=lambda x:html.escape(str(x))
    parts=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>评论项目归属：10条实测对照</title><style>body{font:16px/1.7 system-ui;max-width:1250px;margin:36px auto;padding:0 24px;color:#18314c}table{border-collapse:collapse;width:100%;font-size:14px}td,th{border:1px solid #cbd7e5;padding:10px;vertical-align:top;text-align:left}th{background:#edf4fc}.note{background:#fff5d9;padding:15px}details{margin:20px 0}summary{cursor:pointer;font-weight:bold}.source{white-space:pre-wrap;background:#f6f8fb;padding:14px;overflow-wrap:anywhere}</style><h1>评论先判断、父文再补充：10条实测</h1>']
    parts.append('<p>本次复用原有切片和标签，只复核项目归属。10条来自原587条，不新增重复来源。</p>')
    parts.append(f'<p class="note">10条中，{changed}条来源的项目分配发生改变；{len(excluded)}条属于四项目外，移出有效计数但保留完整记录。修正版有效来源{len(accepted)}条＝{counts.get("文章",0)}篇文章＋{counts.get("评论",0)}条评论。其余466条评论尚未完成本轮逐条复核，1000条目标尚未完成。</p>')
    parts.append('<h2>采用的规则</h2><ol><li>先只看评论：明确谈A楼盘就归A，不受父文B干扰。</li><li>评论没说清：父文只主讲一个具体盘时直接继承。</li><li>父文谈多个盘：结合评论指代消歧，不能随便选；四项目外不硬塞。</li><li>同条合并评论里的每个标签分别找对象，不把全部标签挂到全部提及项目。</li></ol>')
    parts.append('<h2>逐条对照</h2><table><tr><th>来源</th><th>测试情形</th><th>标签</th><th>原项目</th><th>新项目</th><th>方式</th></tr>')
    methods={'comment_explicit':'评论自身明确','unique_parent_inherited':'父文唯一项目继承','parent_context_resolved':'父文辅助消歧','ambiguous':'无法唯一确定'}
    for r in rows:
        for d in r['标签对照']:
            parts.append('<tr>'+''.join('<td>'+esc(x)+'</td>' for x in [r['record_id'],r['抽样类型'],d['标签名'],'、'.join(d['修改前项目']),'、'.join(d['修改后项目']) or '不强行归属',methods[d['归属方式']]])+'</tr>')
    parts.append('</table><h2>原文与判定依据</h2>')
    for r in rows:
        parts.append(f'<details><summary>{esc(r["record_id"])}｜{esc(r["抽样类型"])}</summary><p>父文标题：{esc(r["父文标题"])}</p><div class="source">{esc(r["评论原文"])}</div>')
        for d in r['标签对照']:parts.append(f'<p><b>{esc(d["标签名"])}</b>：{esc(d["理由"])}<br>项目证据：{esc("；".join(d["引文"]))}</p>')
        parts.append('</details>')
    c=cost();parts.append('<h2>验证与消耗</h2><p>10条的来源原文、切片、标签内容及正式响应证据均通过程序重放；Codex已对以上案例做原文核对。定向挑选的小样本不能代表全量准确率，也不是人工金标准验收。</p>')
    parts.append(f'<p>本轮正式账本：输入{c.get("prompt_tokens",0):,} Token，输出{c.get("completion_tokens",0):,} Token，总计{c.get("total_tokens",0):,} Token；估算费用¥{c.get("estimated_yuan",0):.6f}。另有{c["attempts_with_unknown_usage"]}次尝试无usage，未按0计。没有与旧流程做同输入的完整计费对照，故不宣称节省百分比。</p>')
    parts.append('<p>全量587条原库存保持不变；本页对应修正版缓存，不是1000条最终交付。</p></html>')
    page=q.OUT/'评论项目归属_10条测试对照.html'
    # apply_patch is used by the caller to write this generated artifact.
    patch='*** Begin Patch\n*** Add File: '+str(page).replace('\\','/')+'\n'+''.join('+'+line+'\n' for line in ''.join(parts).splitlines())+'*** End Patch\n'
    q.save(q.WORK/'html_render_payload.json',{'path':str(page),'html':''.join(parts)})
    print(json.dumps(meta|{'verification_passed':True,'cost':c},ensure_ascii=False))

if __name__=='__main__':main()
