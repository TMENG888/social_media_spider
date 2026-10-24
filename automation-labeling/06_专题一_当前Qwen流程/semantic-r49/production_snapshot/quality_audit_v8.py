"""Broader QA flags; counts are not precision/recall estimates."""
import argparse
import json
import re
from pathlib import Path
import delivery_v8 as v


def normalized(text):return re.sub(r'[\s\W_]+','',str(text or ''),flags=re.UNICODE)


def main():
    p=argparse.ArgumentParser();p.add_argument('--result',type=Path,required=True);args=p.parse_args()
    data=json.loads(args.result.read_text(encoding='utf-8'));products=data['tables']['产品信息单元'];views=data['tables']['观点信息单元']
    flags=[]
    for row in products+views:
        text=row.get('原文摘录',row.get('原始摘录',''))
        headers=re.findall(r'建筑面积[：:]\s*(\d+(?:\.\d+)?)\s*[㎡平]',text)
        if len(set(headers))>1:
            flags.append({'unit_id':row['unit_id'],'问题类型':'多个户型可能被合并','证据':headers,
                '核查理由':'同片含多个独立建筑面积标题；需结合全文判断是否应按户型分片，不能直接按数字机械拆分。'})
        practice=row.get('具体产品做法')
        if practice and len(normalized(practice))>=20 and normalized(practice) in normalized(text):
            flags.append({'unit_id':row['unit_id'],'问题类型':'产品做法疑似截取原文','证据':practice,
                '核查理由':'做法去标点后整体包含于摘录；现有相等检查不覆盖删掉宣传尾句的搬运。需重写并核数值、对象和状态。'})
    deferred=[{'record_id':r['document']['record_id'],'choice_key':item['choice_key'],'原因':item['reason'],
        '原模型理由':item['original_label'].get('why')} for r in data['results'] for item in (r.get('reviewed') or {}).get('deferred_evidence') or []]
    diagnostics={'no_valid_label_units':sum(not r['标签明细'] for r in products+views),
        'empty_product_practice':sum(not r['具体产品做法'] for r in products),'empty_view_summary':sum(not r['观点摘要'] for r in views),
        'multi_label_units':sum(len(r['标签明细'])>1 for r in products+views),
        'broader_qa_flags':flags,'deferred_labels':deferred,
        'note':'以上是规则触发的复查线索，不是误标/漏标率，也不把空标签全部视作漏标。'}
    v.base.save_json(args.result.parent/'quality_diagnostics.json',diagnostics)
    for name,rows in [('质量复查线索',flags),('证据待复核标签',deferred)]:
        data['tables'][name]=rows;data['schemas'][name]=list(rows[0]) if rows else ['说明']
        v.base.write_csv(args.result.parent/(name+'.csv'),rows,data['schemas'][name])
    v.base.save_json(args.result,data)
    print(v.base.dumps({k:val for k,val in diagnostics.items() if k not in {'broader_qa_flags','deferred_labels'}}))
    print(v.base.dumps({'broader_qa_flags':len(flags),'deferred_labels':len(deferred),'examples':flags[:4]}))


if __name__=='__main__':main()
