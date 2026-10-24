"""Quality diagnostics, not a ground-truth precision/recall evaluation."""
import argparse
import json
from collections import Counter
from pathlib import Path
import delivery_v4 as v


def evaluate(data):
    products=data['tables']['产品信息单元'];views=data['tables']['观点信息单元'];units=products+views
    categories={'生成/校验置信度不足':['置信度','生成置信度'],
                '项目或主体信息不明确':['项目归属','项目未明确','项目缺少','品牌/经营主体','经营主体缺少','城市未明确'],
                '摘要或产品做法需处理':['摘要待复核','具体产品做法为空','直接复制','原文外数字'],
                '标签证据或定义争议':['标签硬约束','标签证据不是','不支持的标签','无有效标签','没有有效标签','语义校验未明确支持'],
                '独立校验发现遗漏':['未覆盖内容','漏标'],
                '语义验收未通过':['模型语义验收未通过'],
                '语义切片较长':['超过600字']}
    counts={name:sum(any(term in u['备注'] for term in terms) for u in units) for name,terms in categories.items()}
    comments=[r for r in data['results'] if r['document']['kind']=='评论']
    return {'unit_counts':{'product':len(products),'article_view':sum(u['来源类型']=='文章' for u in views),
                           'comment_view':sum(u['来源类型']=='评论' for u in views)},
            'automatic_pass':sum(u['验收状态']=='自动通过' for u in units),
            'human_review':sum(u['验收状态']=='需人工审核' for u in units),
            'manual_reason_counts_overlapping':counts,
            'empty_product_practice':sum(not u['具体产品做法'] for u in products),
            'empty_view_summary':sum(not u['观点摘要'] for u in views),
            'no_valid_label_units':sum(not u['标签明细'] for u in units),
            'multi_label_units':sum(len(u['标签明细'])>1 for u in units),
            'comments_reviewed_as_whole':len(comments),'comments_with_unit':sum(bool(r['rows']) for r in comments),
            'comments_excluded_with_audit':sum(not r['rows'] and bool(r['audit']) for r in comments),
            'real_article_source_coverage':dict(Counter(r['document']['field'] for r in data['results'] if r['document']['kind']=='文章')),
            'limitations':['无人工金标准，不能宣称准确率/召回率。','本批未抽到OCR主体，也没有多项目评论，相关边界仅做程序回归。',
                           '自动通过只是机器验收；低置信度、漏标争议和缺失文案仍须人工审核。']}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('input',type=Path);p.add_argument('--output',type=Path);args=p.parse_args()
    result=evaluate(json.loads(args.input.read_text(encoding='utf-8')))
    if args.output:v.save_json(args.output,result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
