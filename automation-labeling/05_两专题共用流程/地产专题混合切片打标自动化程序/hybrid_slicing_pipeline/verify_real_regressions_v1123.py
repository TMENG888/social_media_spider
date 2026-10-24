"""Source-specific observed regressions, independent of model confidence.

These anchors cover confirmed defects only, not overall precision/recall.
Empty summaries do not count as repairs. No fabricated golden replacement tags.
"""
import argparse
import json
import re
from pathlib import Path
from prose_header_ambiguity import issues as header_issues
from prose_speaker_entity_scope import issues as speaker_entity_issues


def inspect(data):
    results={r['document']['record_id']:r for r in data.get('results',[])}
    errors=[];checks=[]
    def require(name,passed,detail):
        checks.append({'check':name,'passed':bool(passed),'detail':detail})
        if not passed:errors.append(name+': '+detail)
    expected={'T2-2188228096999350274','T2-C-7963753211120747283','T2-C-7963753211120747270',
              'T2-C-7963753211120747272','T2-C-7963753211120747418','T2-8000912876517503117'}
    for rid in sorted(expected):
        require(rid+' 来源必须存在',rid in results,'缺少真实回归来源，不能用未检查冒充通过')
    rid='T2-2188228096999350274'
    if rid in results:
        rows=results[rid]['rows']
        for row in rows:
            tags={t['标签路径ID'] for t in row['标签明细']}
            excerpt=row['原始摘录'];summary=row['观点摘要'] or ''
            require(row['unit_id']+' 大平层不误作大高','VOC-0171' not in tags,'本来源只明示大平层，不明示大高住宅类型')
            if any(t in excerpt for t in ('五重静界','三园十八景')):
                require(row['unit_id']+' 室内/园林不误标外立面',not tags.intersection({'VOC-0415','VOC-0417'}),'相应证据没有明确建筑外立面对象')
            if '客群跨度' in excerpt:
                require(row['unit_id']+' 客群定位不冒充本人关注','VOC-0076' not in tags,'第三方产品定位不是客户本人近期关注项目')
            if '三园十八景' in excerpt:
                require(row['unit_id']+' 园林摘要有效',bool(summary),'摘要留空不算完成对象修复')
                require(row['unit_id']+' 不造复合项目名',not any(t in summary for t in ('建发海晏•华润臻澐','建发海晏• 华润臻澐')),'采集标题残留不等于联合项目名')
                require(row['unit_id']+' 不把污染标题转成共同配置',not header_issues(excerpt,summary),'改为与/和不代表完成对象归属修复')
            if '3.4米的层高' in excerpt:
                require(row['unit_id']+' 层高不移植给海晏',bool(summary) and '海晏3.4' not in summary and '海晏层高3.4' not in summary,'需保留有据摘要，不把臻澐3.4米当海晏参数')
        layer=[r for r in rows if '3.4米' in r['原始摘录'] and any(t['标签路径ID']=='VOC-0195' for t in r['标签明细'])]
        require('连续层高参数及解释不过细重复',len(layer)==1,f'含3.4米且标层高的单元数={len(layer)}，同一连续对比主题应保留整体')
        require('层高比较不吞并前一客群定位主题',bool(layer) and all(
            '客群跨度' not in r['原始摘录'] and '社区氛围' not in r['原始摘录'] for r in layer),
            '真实原文的客群定位在第3维度，层高与户型在第4维度，不能靠错误合并解决重复')
    rid='T2-C-7963753211120747283'
    if rid in results:
        rows=results[rid]['rows']
        require('短评论完整一行',len(rows)==1 and rows[0]['原始摘录']==results[rid]['document']['text'],'评论不得拆分或改写原文')
        if rows:
            summary=rows[0]['观点摘要'] or ''
            require('短评论有效摘要',bool(summary),'指代不明不能把清楚的短评价摘要留空')
            require('短评论不借父文事实',not any(t in summary for t in ('海淀西','新房','噪音')),'当前评论仅为还好问题不大')
    rid='T2-C-7963753211120747270'
    if rid in results:
        rows=results[rid]['rows']
        require('长多回复评论完整一行',len(rows)==1 and rows[0]['原始摘录']==results[rid]['document']['text'],'完整评论和已有回复仍仅一行')
        if rows:
            tags={t['标签路径ID'] for t in rows[0]['标签明细']}
            require('价格及关注项目标签恢复',{'VOC-0074','VOC-0076'}<=tags,'明确贵/关注项目事实不能因证据编号协议失败丢失')
            require('长评论有效摘要',bool(rows[0]['观点摘要']),'留空不算摘要修复')
            require('评论昵称不变成房源项目',not speaker_entity_issues(results[rid]['document']['text'],rows[0]['观点摘要']),
                    '评论标题发言者与正文评价对象不同，不能把仅见标题的昵称列成房源名单；嘉棠在此真实原文中是房源对象，不是昵称')
            require('明确价格负态度不被整体中性抹掉','负向' in (rows[0]['情绪态度'] or ''),'多发言者态度须保留明确抱怨，不以整体基调覆盖')
    rid='T2-8000912876517502948'
    if rid in results:
        rows=results[rid]['rows']
        require('西冉不是臻澐别名',not any('臻澐' in (r['观点摘要'] or '') for r in rows),'全文未明示臻澐，不能移植项目身份')
        transport=[r for r in rows if '田村站' in r['原始摘录']]
        require('板块明确地铁配套不漏标',bool(transport) and any(t['标签路径ID']=='VOC-0142' for r in transport for t in r['标签明细']),
                '字典未要求特定在售房源，田村站及6号线有明确原文依据')
    for rid in ('T2-C-7963753211120747272','T2-C-7963753211120747418'):
        if rid not in results:continue
        rows=results[rid]['rows']
        require(rid+' 评论完整一行',len(rows)==1 and rows[0]['原始摘录']==results[rid]['document']['text'],
                '有效评论须保留已有回复，不拆分或修改原文')
        if not rows:continue
        summary=rows[0]['观点摘要'] or ''
        require(rid+' 评论摘要非空',bool(summary),'空摘要不能证明已解决错归属或遗漏')
        if rid.endswith('7272'):
            require('噪音评论保留有限生活影响限定',any(t in summary for t in
                ('不影响生活','不至于影响生活','不太影响生活','生活不受影响','未影响生活','对生活无影响','生活影响不大')),
                '半壁店回复明确听得见但不影响生活，不能仅保留响/害怕而丢掉限制程度')
            require('模糊大小比较不补成房源或周边楼盘',not any(t in summary for t in
                ('小楼盘','小房源','周边楼盘','周边小区')),
                'testo只说比这小多了的，并未给出周边位置或楼盘类别；不能把其他发言者提到小区当作该句对象证据')
        if rid.endswith('7418'):
            require('昵称不证明置业顾问身份',not any(t in summary for t in ('置业顾问','经纪人','销售人员','中介','置业方','销售方','房产方')),
                    '原文只有昵称和项目架桥回复，未明示职业身份')
    rid='T2-8000912876517503117'
    if rid in results:
        rows=results[rid]['rows']
        tags={t['标签路径ID'] for row in rows for t in row['标签明细']}
        require('240平方米户型产品事实不因客户错标而丢失',{'VOC-0186','VOC-0203','VOC-0208'}<=tags,
                '240㎡建筑面积、9.2米宽厅及3卫均为明确产品配置')
        require('卖方产品广告不冒充本人购房关注',not tags.intersection({'VOC-0068','VOC-0069','VOC-0070'}),
                '全文仅为洋房格局和精装广告，未表达客户本人的物业形态、户型或精装关注')
    rid='T2-7055232109415196221'
    if rid in results:
        result=results[rid];rows=result['rows']
        headers=re.findall(r'【[^】]+】',result['document']['text'])
        for row in rows:
            excerpt=row['原始摘录']
            require(row['unit_id']+' 房源对象不串联',sum(h in excerpt for h in headers)<=1,
                    '此文为多个不同项目房源清单，不是同主题双项目比较，不跨两个房源标题合片')
        zhenyun=[row for row in rows if '【华润臻澐】' in row['原始摘录']]
        require('房源清单臻澐明确层高不漏标',bool(zhenyun) and any(
            tag['标签路径ID']=='VOC-0195' for row in zhenyun for tag in row['标签明细']),
            '当前房源明确3.3米层高，不能因为标签证据或对象协议失败使全部标签丢失')
        for row in zhenyun:
            summary=row['观点摘要'] or ''
            require(row['unit_id']+' 房源摘要有效',bool(summary),'摘要为空不是对象映射或打标修复成功')
            require(row['unit_id']+' 臻澐不借用其他房源层高',not any(v in summary for v in ('3.4米','3.9米','4.8米')),
                    '臻澐当前房源明示3.3米，不移植恒基、长安府或格拉斯参数')
    for suffix, forbidden, required, explanation in [
        ('7273', ['海宸北侧虽稍好但仍有巨山路噪音'], [], '不能将另一地块的巨山路及通勤评价套到海宸北侧'),
        ('7275', ['堵车时噪音更大','堵车时更甚'], [], '堵车与噪音并列，不能补因果'),
        ('7276', ['觉得尚可','可以接受'], [], '未听过且二选一相对更好不等于实际接受'),
        ('7277', ['噪音','噪声','声音'], [], '仅分享大飞机视频，未查看视频不能补声音判断'),
        ('7284', [], ['吹雪'], '核心具体事件不可仅用经验附和替代'),
    ]:
        rid='T2-C-796375321112074'+suffix
        if rid not in results:continue
        rows=results[rid]['rows'];summary=rows[0].get('观点摘要') or '' if rows else ''
        require(rid+' 新增实读语义回归',bool(summary) and not any(x in summary for x in forbidden)
                and all(x in summary for x in required),explanation+'；空摘要不是修复成功')
    return {'checks':checks,'errors':errors,'scope':'已观察真实来源错误锚点；不是全样本精确率、召回率或人工金标准'}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('input',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();report=inspect(json.loads(args.input.read_text(encoding='utf-8')))
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'checked':len(report['checks']),'errors':report['errors']},ensure_ascii=False))
    raise SystemExit(bool(report['errors']))
