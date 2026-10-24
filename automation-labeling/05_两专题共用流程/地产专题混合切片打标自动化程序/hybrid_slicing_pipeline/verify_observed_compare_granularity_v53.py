"""Observed semantic comparison axes, never a production keyword boundary."""
import argparse,json
from pathlib import Path

def inspect(data):
    found=[r for r in data.get('results',[]) if r['document']['record_id']=='T2-2188228096999350274']
    checks=[]
    def add(name,ok,detail):checks.append({'check':name,'passed':bool(ok),'detail':detail})
    add('固定对比文章存在',len(found)==1,'缺失来源不能规避粒度测试')
    if found:
        r=found[0];quotes=[row.get('原始摘录','') for row in r['rows']]
        add('层高参数及紧接净高解释保持完整',any('主力楼栋3.4米' in q and '室内净高仍能保持在3米以上' in q for q in quotes),
            '实读此处是同一层高参数及装修后净高解释，不应成为重复介绍3.4米层高的两行')
        gardens=[q for q in quotes if '三园十八景' in q]
        pools=[q for q in quotes if '恒温泳池' in q]
        add('园林比较和会所设施不混为单一比较轴',bool(gardens) and bool(pools)
            and not any('三园十八景' in q and '恒温泳池' in q for q in quotes),
            '已实读两项目园林配置和两项目会所面积/设施，属于景观与会所两个具体对象；同一会所的多设施可以多标签一行，不按标签数拆分')
        add('另一项目园林与会所也逐对象分开',any('王府中式园林' in q for q in quotes)
            and any('下沉会所3600㎡' in q for q in quotes)
            and not any('王府中式园林' in q and '下沉会所3600㎡' in q for q in quotes),
            '新增实际另一项目锚点：只分开臻澐一侧不足以证明同一篇两个项目均已区分园林和会所；不能将海晏全部统称clubhouse')
    return {'checks':checks,'errors':[c['check'] for c in checks if not c['passed']],
            'scope':'一篇已观察文章的连续比较对象锚点，不是全样本粒度评估'}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('input',type=Path);p.add_argument('--output',required=True,type=Path)
    a=p.parse_args();report=inspect(json.loads(a.input.read_text(encoding='utf-8')))
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'checked':len(report['checks']),'errors':report['errors']},ensure_ascii=False))
    raise SystemExit(bool(report['errors']))
