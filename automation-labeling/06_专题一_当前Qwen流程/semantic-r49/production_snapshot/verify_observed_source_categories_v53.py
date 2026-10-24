"""Independent source-specific semantic category regression; read-only rows."""
import argparse,json
from pathlib import Path

def inspect(data):
    checks=[]
    add=lambda name,ok,detail:checks.append({'check':name,'passed':bool(ok),'detail':detail})
    found=[r for r in data.get('results',[]) if r['document']['record_id']=='T2-2188228096999350274']
    add('固定对比文章存在',len(found)==1,'缺失困难来源不算通过')
    if found:
        r=found[0]
        rows=[row for row in r['rows'] if '臻澐的精装逻辑' in row.get('原始摘录','')]
        add('已观察精装事实落入正式单元',bool(rows),'不删除整个困难片以规避错标核验')
        for row in rows:
            ids={t['标签路径ID'] for t in row.get('标签明细',[])}
            quote=row['原始摘录']
            # Scope the anchor to this exact objective configuration comparison.
            pure=('更贴合互联网客群的使用习惯' in quote and '各有侧重' in quote
                  and '我关注' not in quote and '我们考虑' not in quote)
            add('客观精装比较不充当本人购房关注',pure and not(ids & {'VOC-0070','VOC-0071','VOC-0072','VOC-0073','VOC-0076'}),
                '实读此段只分析两个项目配置/客群适配，未记述本人关注或选择过程。其他真正客户评论不受此锚点替代。')
            add('一般配置介绍不充当销售承诺经历',pure and 'VOC-0492' not in ids,
                '实读此段没有售前咨询、到访、签约或销售承诺经历；不能凭装标一词制造服务事件。')
            add('泛称厨电品牌不推断具体烟机灶具',pure and 'VOC-0253' not in ids,
                '实读此段只泛称厨电卫浴品牌层级，没有明确具体油烟机或燃气灶；工法文明确烟机的事实仍应允许独立核查。')
    return {'checks':checks,'errors':[c['check'] for c in checks if not c['passed']],
            'scope':'单个已观察客观精装比较片的定义类别锚点，不是总体精确率/召回率'}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('input',type=Path);p.add_argument('--output',required=True,type=Path)
    a=p.parse_args();report=inspect(json.loads(a.input.read_text(encoding='utf-8')))
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'checked':len(report['checks']),'errors':report['errors']},ensure_ascii=False))
    raise SystemExit(bool(report['errors']))
