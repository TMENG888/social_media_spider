"""A/B parallel ablation and C union verification on frozen MapReduce units.

No source-boundary edits; project context is independently reviewed and common
to all three variants. Baseline remains default. Literal evidence required.
"""
import argparse
import copy
import json
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
import delivery_v76 as baseline
import delivery_v11 as pipeline
import mapreduce_v76 as mr
from bounded_visible_contract_v60 import review
from comment_identity_protocol_v59 import obj, TEXT
from evaluate_independent_label_anchors_v59 import evaluate
from compare_mapreduce_v76 import EXTRA, stats

VERSION='v78.1-context-and-full-dictionary-ablation-20261010'
CONF={'type':'number','minimum':0,'maximum':1}
IDS=['T1-182247585093626012','T1-75441','T1-7868135928622720541',
    'T2-2188228096999350274','T2-8000912876517502948','T2-8000912876517503117',
    'T2-8000912876517503108','T2-7055232109415196221',
    'T2-C-7963753211120747277','T2-C-7963753211120747276',
    'T2-C-7963753211120747268','T2-C-7963753211120747282',
    'T2-C-7963753211120747279','T2-C-7963753211120747192',
    'T2-C-7963753211120747186','T2-C-7963753211120747283',
    'T2-C-7963753211120747285','T2-C-7963753211120747271']

SYSTEM='''逐项检查本批标签定义与完整文章/完整评论中的实际事实，不做切片，不改原文。
原切片编号为交付位置，不限制查全文识别项目与对象；属性事实必须落在相应切片里。
对象上下文可从全文前文承接，但遇到项目/户型/部位切换就停止，不能借其他切片属性。
对于本批每个标签列入checked_keys一次，所有有据事实在对应unit_id输出labels，可一片多标签。
按完整路径、强调方向和说明判断，不按词面，不因候选近似就凑标签。例子不是必须逐字出现。
尺寸必须绑定正确对象；住宅整体面积不支持餐厅面积。3卫明确支持卫生间数量3。
地漏的存水弯、自动补水、防返味配置/工法应按标签定义检查，不要求证据句重复卫生间。
地铁站远或步行十余分钟仍有地铁事实；客户评论谈地铁重要性应检查对应购房关注点，不只家庭人数。
法式装修是装修风格，不是明确色彩；住宅层高不是土地规划层高。未来交房不是准时交付业绩。
只有飞机视频、没有声音解析或噪音描述，不能推断交通噪音；明确户外听得到/室内听不到属于噪音话题。
父文章只可确认评论指代的身份，不能给评论补不存在的设施/态度/噪音。评论主评和所有回复一起检查。
营销配置不代表客户需求，客户本人提问保留提问性质，不改成确定事实。
property_quote逐字引用对应切片中的最短充分属性证据，object_quote逐字引用全文中的对象证据。
why只给最终定义理由，不写过程；没有适用标签允许空，不为了补全输出低置信度虚构占位。'''

def schema(index):
    return obj({'checked_keys':{'type':'array','items':{'type':'string','enum':list(index)}},
        'labels':{'type':'array','items':obj({'unit_id':TEXT,
            'choice_key':{'type':'string','enum':list(index)},'property_quote':TEXT,
            'object_quote':TEXT,'why':TEXT,'confidence':CONF})}})

def units(result):
    return [{'unit_id':r['unit_id'],'text':r.get('原文摘录',r.get('原始摘录')),
             'start':t['起点'],'end':t['终点']} for r,t in zip(result['rows'],result['traces'])]

def definitions(index):
    return [{'choice_key':k,'path':[t.get('l'+str(i)) for i in range(1,6)],
        '标签强调方向':t['emphasis'],'打标说明':t['instruction']} for k,t in index.items()]

def payload(result,index):
    doc=result['document']
    return {'source_text':doc['text'],'source_type':doc['kind'],'research_topic':doc['topic'],
        'current_units':units(result),'all_branch_labels':definitions(index),
        'parent_identity_context':pipeline.p.base.choose_source(doc['parent'])[1] if doc['kind']=='评论' else ''}

def valid_labels(result,raw,index):
    quotes={u['unit_id']:u['text'] for u in units(result)}; accepted=[]; errors=[]
    if len(raw['checked_keys'])!=len(index) or set(raw['checked_keys'])!=set(index):
        return [],['分支未完整检查字典']
    for item in raw['labels']:
        if item['unit_id'] not in quotes or item['property_quote'] not in quotes.get(item['unit_id'],''):
            errors.append('属性证据无法定位：'+item['unit_id']);continue
        if item['object_quote'] not in result['document']['text']:
            errors.append('对象证据不在全文');continue
        if item['confidence']>=.90:accepted.append(item)
    return accepted,errors

def route_a(result,index,runner):
    offered=set()
    for r in result['rows']:
        offered.update('D'+t['标签路径ID'].split('-')[1] for t in r['标签明细'])
    offered.update(p['choice_key'] for p in result.get('mapreduce_audit',{}).get('proposals',[]))
    selected={k:index[k] for k in sorted(offered) if k in index}
    if not selected:return [],[],[],[]
    raw,cc,aa,ee=review(SYSTEM,payload(result,selected),schema(selected),result['document'],'路线A全文上下文救回-v78',runner)
    if raw and not ee:
        labels,ve=valid_labels(result,raw,selected);ee+=ve
    else:labels=[]
    return labels,cc,aa,ee

def route_b(result,index,runner):
    def one(group):
        sub=group['index'];raw,cc,aa,ee=review(SYSTEM,payload(result,sub),schema(sub),result['document'],
            '路线B切片全字典分支-v78',runner)
        labels=[]
        if raw and not ee:
            labels,ve=valid_labels(result,raw,sub);ee+=ve
        return labels,cc,aa,ee
    with ThreadPoolExecutor(max_workers=10) as pool:out=list(pool.map(one,mr.groups(index)))
    return tuple([v for part in out for v in part[i]] for i in range(4))

VERIFY_SYSTEM='''独立核查每条候选标签与实际对象及属性，不默认相信候选或旧标签。
全文只帮助对象定位，标签的属性证据必须在指定切片中。完整路径和定义都要满足。
不支持、证据不足是合法结果，不能为标签数量提高信心。每个proposal_id恰好返回一次。
支持必须给原文逐字property_quote及object_quote，否决可返回空引用；支持需对象、属性、模态、无推断全成立。
卫生间防臭方案可跨前句承接对象，但不能借厨房做法；蒂森克虏伯换日立是品牌变更，不是质量实测。
只有飞机10s视频文字不证明噪音，不能借父文噪音；否认室内听到但明确户外可闻仍是噪音话题。
营销看房验资不是自述购房预算；4人是人数不是人口增加。未来交房不是准时交付。
房源3.3米层高不是土地层高；法式风格没有颜色不支持色彩。高速附近噪音不证明高速入口。
地铁距离远仍支持周边轨道交通，客户谈家人需要地铁支持交通配套关注，但不证明具体站点距离。
why只写最终证据理由，不输出内部过程。'''

def route_c(result,index,a,b,runner):
    union={}
    for item in a+b:
        key=(item['unit_id'],item['choice_key'])
        union.setdefault(key,item)
    for row,trace in zip(result['rows'],result['traces']):
        for tag in row['标签明细']:
            key='D'+tag['标签路径ID'].split('-')[1]
            union.setdefault((row['unit_id'],key),{'unit_id':row['unit_id'],'choice_key':key,
                'property_quote':row.get('原文摘录',row.get('原始摘录')),'object_quote':row.get('原文摘录',row.get('原始摘录')),
                'why':'旧版候选，必须独立核查','confidence':0})
    proposals=[dict(v,proposal_id=str(i)) for i,v in enumerate(union.values())]
    if not proposals:return [],[],[],[]
    def one(batch):
        keys=[p['proposal_id'] for p in batch]
        s=obj({'decisions':{'type':'array','items':obj({'proposal_id':{'type':'string','enum':keys},
            'status':{'type':'string','enum':['supported','unsupported','uncertain']},
            'property_quote':{'type':'string'},'object_quote':{'type':'string'},
            'why':TEXT,'confidence':CONF})}})
        req=payload(result,{p['choice_key']:index[p['choice_key']] for p in batch})
        req['proposals']=batch
        raw,cc,aa,ee=review(VERIFY_SYSTEM,req,s,result['document'],'路线C联合候选独立核验-v78',runner)
        selected=[]
        if raw and not ee:
            if len(raw['decisions'])!=len(keys) or {d['proposal_id'] for d in raw['decisions']}!=set(keys):
                ee.append('独立核验遗漏候选')
            else:
                lookup={p['proposal_id']:p for p in batch}
                for d in raw['decisions']:
                    if d['status']=='supported' and d['confidence']>=.90:
                        item=dict(lookup[d['proposal_id']],**{k:d[k] for k in ('property_quote','object_quote','why','confidence')})
                        selected.append(item)
        return selected,cc,aa,ee
    batches=[proposals[i:i+24] for i in range(0,len(proposals),24)]
    with ThreadPoolExecutor(max_workers=10) as pool:out=list(pool.map(one,batches))
    selected,cc,aa,ee=tuple([v for part in out for v in part[i]] for i in range(4))
    # Literal evidence is rechecked after independent semantic selection.
    selected,ve=valid_labels(result,{'checked_keys':list(index),'labels':selected},index)
    return selected,cc,aa,ee+ve

PROJECT_SYSTEM='''只核查每个现有切片的事实/评价实际属于哪个项目，不生成配置标签。
读取全文，记录项目切换。前文对象可连续继承，不能遇到切换后仍沿用。多项目比较分别确认。
切片开头介绍两个比较项目不意味着后续西冉参数属于保利熙瑞；以参数/评价实际对象为准。
海晏可在全文建发海晏身份有据时对应同一项目，不能仅因当前候选只有一个就归属。
对评论允许父文身份关系消解指代，不能用父文替代评论自身事实，不强填项目。
每个unit_id恰好一次；targets空表示未确认。name必须是全文或有据简称关系指向的实际名称。
identity_quote逐字引用全文身份原文；relation_quote逐字引用当前切片原文证明其评价对象。
字典外西冉地块保留真实名称，绝不编造成竞品ID。why说明实际证据及如何排除其他对象。'''
TARGET=obj({'name':TEXT,'identity_quote':TEXT,'relation_quote':TEXT,'why':TEXT,'confidence':CONF})

def project_review(result,business,runner):
    if result['document']['topic']!=pipeline.p.base.T2:return {},[],[],[]
    s=obj({'units':{'type':'array','items':obj({'unit_id':TEXT,'targets':{'type':'array','items':TARGET}})}})
    req=payload(result,{})
    req['projects']=[{'name':p['name'],'aliases':p['aliases']} for p in business['projects']]
    raw,cc,aa,ee=review(PROJECT_SYSTEM,req,s,result['document'],'公共项目上下文归属-v78',runner)
    if not raw or ee:return {},cc,aa,ee
    expected={u['unit_id']:u['text'] for u in units(result)}
    if len(raw['units'])!=len(expected) or {u['unit_id'] for u in raw['units']}!=set(expected):
        return {},cc,aa,ee+['项目核验未覆盖切片']
    # Second independently worded check. No confidence repair on rejection.
    vraw,vc,va,ve=review(PROJECT_SYSTEM+'\n本轮独立审查suggestions，只保留能被原文确认的关系，可否决旧建议，不默认相信名称。',
        dict(req,suggestions=raw),s,result['document'],'公共项目归属独立验收-v78',runner)
    cc+=vc;aa+=va;ee+=ve
    if not vraw or ve:return {},cc,aa,ee
    if len(vraw['units'])!=len(expected) or {u['unit_id'] for u in vraw['units']}!=set(expected):
        return {},cc,aa,ee+['项目独立验收未覆盖切片']
    accepted={}
    doc=result['document'];full=doc['text']
    if doc['kind']=='评论':full+='\n'+pipeline.p.base.choose_source(doc['parent'])[1]
    for u in vraw['units']:
        good=[]
        for t in u['targets']:
            if t['confidence']<.90 or t['identity_quote'] not in full or t['relation_quote'] not in expected[u['unit_id']]:continue
            matches=[p for p in business['projects'] if t['name']==p['name'] or t['name'] in p['aliases']]
            if len(matches)>1:continue
            p=matches[0] if matches else None
            good.append(dict(t,id=p['id'] if p else None,role=p['role'] if p else '其他',name=p['name'] if p else t['name']))
        accepted[u['unit_id']]=good
    return accepted,cc,aa,ee

def apply(result,labels,projects,index,calls,audit,route,errors):
    out=copy.deepcopy(result);by=defaultdict(dict)
    for l in labels:by[l['unit_id']].setdefault(l['choice_key'],l)
    for row,trace in zip(out['rows'],out['traces']):
        uid=row['unit_id']; selected=by[uid]
        # Protocol failure: original source remains untouched, not silently empty.
        if errors:
            row['备注']+='；实验审核协议未完整通过，保留旧标签待核'
        else:
            row['标签明细']=[pipeline.p.base.label_json(index[k]) for k in selected]
            row['打标说明']='\n'.join(index[k]['tag_id']+'｜对象证据：'+l['object_quote']+'｜属性证据：'+l['property_quote']+'｜理由：'+l['why'] for k,l in selected.items())
            trace['实验标签证据']=list(selected.values())
        if uid in projects:
            targets=projects[uid]
            if out['document']['kind']=='评论':
                row.update(project_id=[t['id'] for t in targets],项目名称=[t['name'] for t in targets],项目角色=[t['role'] for t in targets])
            elif len(targets)==1:
                t=targets[0];row.update(project_id=t['id'],项目名称=t['name'],项目角色=t['role'])
            else:row.update(project_id=None,项目名称='待判断',项目角色='其他')
            trace['实验项目归属']=targets
        row['验收状态']='需人工审核'
        row['备注']+='；'+route+'实验输出，未进行独立人工金标准验收；原切片边界和文案暂保留'
        trace['实验版本']=VERSION
    out['calls']+=calls;out['experiment_audit']=audit;out['experiment_errors']=errors
    return out

def main():
    p=argparse.ArgumentParser();p.add_argument('--baseline',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True)
    args=p.parse_args();baseline.activate()
    read=lambda f:json.loads(f.read_text(encoding='utf-8'))
    before=read(args.baseline); selected=[r for r in before['results'] if r['document']['record_id'] in IDS]
    if len(selected)!=len(IDS):raise ValueError('Fixed experimental sources missing')
    taxonomy=pipeline.p.base.load_taxonomy(pipeline.p.v.legacy.TAXONOMY);business=before['business']
    runner=pipeline.p.base.ApiRunner(args.output_dir,10,key=os.getenv('YS_LLM_API_KEY'))
    signature=pipeline.p.base.digest(Path(__file__).read_text(encoding='utf-8'))
    def work(result):
        file=args.output_dir/'documents'/(pipeline.p.base.digest({'implementation':signature,'result':result})+'.json')
        if file.exists():return read(file)
        doc=result['document'];index=pipeline.p.v.registry(taxonomy,doc['topic'])
        with ThreadPoolExecutor(max_workers=3) as pool:
            fa=pool.submit(route_a,result,index,runner);fb=pool.submit(route_b,result,index,runner)
            fp=pool.submit(project_review,result,business,runner)
            a,ac,aa,ae=fa.result();b,bc,ba,be=fb.result();projects,pc,pa,pe=fp.result()
        c,cc,ca,ce=route_c(result,index,a,b,runner)
        output={route:apply(result,ll,projects,index,calls+pc,{'labels':audit,'projects':pa},route,ee+pe)
            for route,ll,calls,audit,ee in [('A',a,ac,aa,ae),('B',b,bc,ba,be),('C',c,ac+bc+cc,aa+ba+ca,ce)]}
        pipeline.p.base.save_json(file,output);return output
    outputs=[]
    with ThreadPoolExecutor(max_workers=10) as pool:
        for f in as_completed([pool.submit(work,r) for r in selected]):
            outputs.append(f.result());print(json.dumps({'completed':len(outputs),'planned':len(selected)}),flush=True)
    order={r['document']['record_id']:i for i,r in enumerate(selected)}
    refs=read(Path(__file__).with_name('independent_label_anchors_v59.json'));refs['anchors']+=EXTRA
    base=dict(before,results=selected)
    reports={'baseline':{'counts':stats(base),'reference':evaluate(base,refs)}}
    for route in 'ABC':
        results=sorted([o[route] for o in outputs],key=lambda r:order[r['document']['record_id']])
        directory=args.output_dir/route
        data=pipeline.p.base.export(directory,results,before['sampling'],taxonomy,business,runner,'api',True)
        data['summary'].update(version='delivery-v76.4-experiment-v78-'+route,planned_articles=8,
            note='针对性18来源并行实验；原切片与文案复用，不是全量重打标或人工准确率。')
        data['execution_manifest']={'requested_record_ids':IDS,'scope':'针对性子集','seed':None}
        pipeline.p.base.save_json(directory/'delivery_results.json',data)
        reports[route]={'counts':stats(data),'reference':evaluate(data,refs),
            'errors':[e for r in results for e in r['experiment_errors']]}
    reports['scope']={'articles':8,'comments':10,'selection':'针对性已知问题，不是随机代表性样本',
        'strategies':'A原提议全文救回；B现切片全字典分支；C联合候选独立核验；项目校正为共同步骤',
        'baseline_default_unchanged':True}
    reports['new_calls']=runner.calls
    pipeline.p.base.save_json(args.output_dir/'experiment_comparison.json',reports)
    for name,r in reports.items():
        if isinstance(r,dict) and 'reference' in r:
            print(json.dumps({'route':name,'counts':r['counts'],'hit':r['reference']['hit_required_tags'],
                'required':r['reference']['processed_required_tags'],'forbidden_hits':r['reference']['forbidden_tag_hits'],
                'errors':len(r.get('errors',[]))},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
