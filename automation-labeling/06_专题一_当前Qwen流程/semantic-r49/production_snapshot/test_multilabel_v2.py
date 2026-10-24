"""Offline historical replay + contract regression; never presents mocks as API runs."""
import argparse
import json
from pathlib import Path
from multilabel_v2 import label_guard, normalize_response, semantic_spans, summary_guard, sentiment, recall, load_taxonomy, T1, T2


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text(encoding='utf-8'))
    tables = fixture['tables']
    main_rows = tables['多标签切片主表']
    associations = tables['标签展开与核对']
    originals = tables['抽取原始行']
    taxonomy = []
    for r in associations:
        taxonomy.append({'tag_id': r['标签路径ID'], 'l1': r['一级标签'], 'l2': r['二级标签'],
                         'l3': r['三级标签'], 'l4': r['四级标签'], 'l5': r['五级标签'],
                         'emphasis': r.get('标签强调方向'), 'instruction': r['打标说明'], 'topics': [r['所属专题']]})
    checks, guards, preslices, replay = [], [], [], []
    def check(name, passed, detail):
        checks.append({'测试项': name, '结果': '通过' if passed else '失败', '说明': detail})
        if not passed:
            raise AssertionError(name + ': ' + detail)
    for row in main_rows:
        text = row['切片内容']
        related = [x for x in associations if x['切片ID'] == row['切片ID']]
        for r in related:
            label = next(x for x in taxonomy if x['tag_id'] == r['标签路径ID'])
            state, reason = label_guard(text, label)
            expected = 'supported' if r['统计计入'] == 1 else 'rejected'
            guards.append({'样例ID': row['切片ID'], '标签ID': label['tag_id'], '标签路径': '→'.join(str(label[f'l{i}']) for i in range(1,6) if label[f'l{i}']),
                           '原标签是否样例保留': r['统计计入'], '新版机器门控': state, '门控原因': reason})
            check(row['切片ID']+'_'+label['tag_id'], state == expected, reason)
        ranges = semantic_spans(text)
        for idx, (start, end) in enumerate(ranges, 1):
            excerpt = text[start:end]
            preslices.append({'样例ID': row['切片ID'], '预切片序号': idx, '起点': start, '终点': end,
                              '原文切片': excerpt, '情绪规则线索': sentiment(excerpt),
                              '状态': '离线规则预切片，未由新API确认'})
        check(row['切片ID']+'_原文位置', all(text[a:b] for a,b in ranges), '所有预切片均为未改写原文的真实子串')
        check(row['切片ID']+'_边界覆盖', all(not text[a:b].strip() for a,b in zip([0]+[e for _,e in ranges], [s for s,_ in ranges]+[len(text)])), '预切片之间只允许留白，不丢弃原文内容')
        original = next(x for x in originals if x['对应切片ID'] == row['切片ID'])
        historical_summary = original.get('观点摘要') or original.get('具体产品做法') or ''
        # Deliberately replay old machine outputs, not improved/human-authored summaries.
        response = {'article_id': row['源表id'], 'slices': [{'start':0,'end':len(text), 'excerpt': text,
                    'project': row['项目'], 'summary': historical_summary,
                    'labels': [{'tag_id':r['标签路径ID'], 'evidence':r.get('对应证据') or text,
                                'support':'supported', 'sentiment':original.get('情绪态度') or '无态度'} for r in related]}]}
        doc = {'article_id': row['源表id'], 'topic': row['所属专题'], 'text': text}
        result = normalize_response(doc, taxonomy, response)
        replay.append({'sample_id': row['切片ID'], 'document': doc, 'result': result})
        check(row['切片ID']+'_不冒充人工', all(s['count_in_statistics']==0 and all(t['count_in_statistics']==0 for t in s['labels']) for s in result['slices']), '历史输出回放全部保持待人工验收')
    doc = {'article_id': 'contract-test', 'topic': T1, 'text': '复兴珑御户型采光良好。'}
    tag = next(x for x in taxonomy if x['tag_id']=='VOC-0191')
    result = normalize_response(doc, taxonomy, {'article_id':'contract-test','slices':[], 'exclusion_reason':'没有有效产品事实'})
    check('合法空结果不复活', result['state']=='excluded' and not result['slices'], '模拟结构边界，不是API返回')
    result = normalize_response(doc, taxonomy, None, 'failed')
    check('API失败不回填', result['state']=='api_failed' and not result['slices'], 'API失败保留文档异常，不生成标签或摘要')
    result = normalize_response(doc, taxonomy, {'article_id':'contract-test','slices':[]})
    check('空结果缺原因', result['state']=='invalid_response', '不能把静默丢失当作正常排除')
    unit = {'start':0,'end':len(doc['text']), 'excerpt':doc['text'], 'project':'复兴珑御','summary':'复兴珑御户型采光良好。',
            'labels':[{'tag_id':tag['tag_id'],'evidence':'采光良好','support':'supported','sentiment':'正向'}]}
    def normalize(unit):
        return normalize_response(doc,taxonomy,{'article_id':doc['article_id'],'slices':[unit]})
    check('正确子串', len(normalize(unit)['slices'][0]['labels'])==1,'有效原文证据可以通过机器门控')
    check('偏移错误阻断', not normalize(dict(unit,start=1))['slices'],'错位原文不得物化')
    check('非法标签阻断', not normalize(dict(unit,labels=[dict(unit['labels'][0],tag_id='VOC-INVALID')]))['slices'][0]['labels'],'未知字典ID不能回退为旧标签')
    check('伪造证据阻断', not normalize(dict(unit,labels=[dict(unit['labels'][0],evidence='不存在的采光证据')]))['slices'][0]['labels'],'标签证据必须是当前切片原文子串')
    check('标签明确否定', not normalize(dict(unit,labels=[dict(unit['labels'][0],support='unsupported')]))['slices'][0]['labels'],'unsupported不会被保留')
    check('摘要新增数字阻断', bool(summary_guard(doc['text'],'复兴珑御每天日照8小时')),'数字缺少原文依据需复核')
    check('摘要失败不复制', bool(summary_guard(doc['text'],'')),'空摘要明确待复核')
    check('正向线索', sentiment('精装配置基本也把后期麻烦省掉了')=='正向','覆盖当前精装案例的正向表述')
    check('混合情绪不投票', sentiment('采光良好但噪声无法根除')=='正负混合','不把正负混合误当中性')
    check('营销主体防改写', bool(summary_guard('想了解价格可以私信我预约看房','购房者关注价格')),'发布者邀请不能变成客户需求')
    # Verify recall exists independently of historical selected tags, using the FULL latest dictionary.
    full = load_taxonomy(Path(__file__).parent/'resources/置地VOC标签体系_两专题打标版.xlsx')
    recall_proposals = []
    for r in main_rows:
        old_ids = {x['标签路径ID'] for x in associations if x['切片ID']==r['切片ID']}
        for label in recall(r['切片内容'], r['所属专题'], full):
            state, reason = label_guard(r['切片内容'], label)
            if state=='supported' and label['tag_id'] not in old_ids:
                recall_proposals.append({'样例ID':r['切片ID'],'标签ID':label['tag_id'],
                                         '候选路径':'→'.join(label[f'l{i}'] for i in range(1,6) if label[f'l{i}']),
                                         '证据门控':state,'说明':'新增召回候选，不是已经验收的新标签；'+reason})
    check('户型重召回非公区', any(x['样例ID']=='MS-003' and '户型' in x['候选路径'] for x in recall_proposals), '从完整最新字典找到户型候选，仍需API/人工验证')
    check('一切片多标签', len(replay[0]['result']['slices'])==1 and len(replay[0]['result']['slices'][0]['labels'])==2,'回放设备案例输出一行两标签')
    check('营销整片排除', not replay[-1]['result']['slices'] and bool(replay[-1]['result']['rejected']),'营销记录不进入有效切片表')
    check('正向与无态度冲突', any('情绪不一致' in issue for s in replay[3]['result']['slices'] for t in s['labels'] for issue in t['issues']), '不覆盖历史情绪，明确送复核')
    args.output_dir.mkdir(parents=True,exist_ok=True)
    payload={'source':fixture['source'], 'mode':'离线规则及历史结果回放；没有新API调用',
             'checks':checks,'guards':guards,'preslices':preslices,'replay':replay,'recall_proposals':recall_proposals,
             'summary':{'sample_groups':len(main_rows),'historical_associations':len(guards),
                        'supported':sum(x['新版机器门控']=='supported' for x in guards),
                        'rejected':sum(x['新版机器门控']=='rejected' for x in guards),
                        'checks_passed':len(checks),'api_calls':0,'cost_yuan':0,'pre_slices':len(preslices),
                        'new_recall_candidates':len(recall_proposals)}}
    (args.output_dir/'offline_evaluation.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(payload['summary'],ensure_ascii=False))


if __name__=='__main__':
    main()
