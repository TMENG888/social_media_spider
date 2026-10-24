"""Confirmed real-source anchors; no automatic edits and no accuracy claim."""
import argparse
import json
from pathlib import Path


def inspect(data):
    results={r['document']['record_id']:r for r in data.get('results',[])}
    checks=[]
    def add(name,passed,detail):
        checks.append({'check':name,'passed':bool(passed),'detail':detail})
    rid='T1-316877139627506490'
    r=results.get(rid)
    add(rid+'来源存在',r is not None,'不得用缺失困难来源冒充修复')
    if r:
        relevant=[u for u in r.get('rows',[]) if '环保材料' in u.get('原文摘录','')]
        add('模糊ASR仍保留明确环保材料和厨房窗户事实',
            bool(relevant) and any(u.get('具体产品做法') and '环保材料' in u['具体产品做法']
                and '厨房' in u['具体产品做法'] and '窗' in u['具体产品做法']
                and any(w in u['具体产品做法'] for w in ('较大','很大','大窗','宽大')) for u in relevant),
            '清空做法或丢弃整条模糊ASR不是修复；明确可读事实需保留')
        prose='\n'.join(u.get('具体产品做法') or '' for u in r.get('rows',[]))
        add('ASR疑词不确定化为全屋风格竹材或过滤窗安装',
            bool(prose) and not any(w in prose for w in ('全屋法式','使用竹材','采用竹材','竹材等','已安装窗户及过滤窗')),
            '真实原文桌子/法式铺的对象不清，竹竹桃楠材质不清，过滤窗装不完不能写成已安装；此为已观察措辞锚点，仍需全文语义人工核对')
        add('放好不升级安装且家具进度不升级整屋半完成',bool(prose)
            and not any(w in prose for w in ('厨房窗户已安装','住宅装修进度为半完成','窗户已安装完毕')),
            '实读原文只说窗户放好，厨房明确属性是较大；桌子附近的装了一半指代不明，不能扩大整屋状态。旧锚点仅查非空和厨房/窗，证据不足，故补强而非宣称47已修复')
    rid='T1-8000912876517502274'
    r=results.get(rid)
    add(rid+'来源存在',r is not None,'不得用缺失困难来源冒充修复')
    if r:
        rows=[u for u in r.get('rows',[]) if '210' in u.get('原文摘录','') and '370' in u.get('原文摘录','')]
        add('明确单项目文章面积切片保留可核身份',bool(rows) and all(
            u.get('品牌组')=='中海' and u.get('项目')=='中海安澜北京' and u.get('城市')=='北京' for u in rows),
            '当前真实全文明示央企中海、中海安澜北京、北京；只核此单项目来源，不向多项目比较推广')
        add('开发公司不误放品牌组',bool(rows) and all(
            u.get('品牌组')!='北京盈臻房地产开发有限公司' for u in rows),
            '品牌与法律开发主体分开，主体未在业务字典获准时仍可待判断')
    return {'checks':checks,'errors':[c['check'] for c in checks if not c['passed']],
            'scope':'两个实读来源的已观察错误锚点，不是全部语义精确率或召回率'}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('input',type=Path)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.input.is_dir():
        data={'results':[json.loads(f.read_text(encoding='utf-8'))
                         for f in sorted(args.input.glob('*.json'))]}
    else:
        data=json.loads(args.input.read_text(encoding='utf-8'))
    report=inspect(data)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'checked':len(report['checks']),'errors':report['errors']},ensure_ascii=False))
    raise SystemExit(bool(report['errors']))


if __name__=='__main__':main()
