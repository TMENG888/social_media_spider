"""Build an evidence-linked regression report; no model calls or production writes."""
import json,hashlib,datetime
from pathlib import Path
import version_contract
R=Path(__file__).parent
OUT=Path('E:/Codex/outputs/20261021_专题一Qwen回归验收')
def read(p):return json.loads(p.read_text(encoding='utf8'))
version='r24';version_contract.verify_frozen()
policy=read(R/'acceptance_policy.json')
rows=[];receipts={}
for b in ['A','B','C']:
    run=R/f'run_{version}'
    e=read(run/f'evaluation_{b}.json');a=read(run/f'audit_{b}.json');v=read(run/f'{b}_export_validation.json')
    score=e['source_tag'];assert e['model_sources']==10
    assert score['precision']>=policy['source_tag_precision_min'] and score['recall']>=policy['source_tag_recall_min']
    assert not e['structural_errors'] and not a['structural_errors']
    assert not e['duplicate_slices'] and not e['empty_practice']
    rows.append(f"| {b} | {score['tp']} / {score['fp']} / {score['fn']} | {score['precision']:.2%} | {score['recall']:.2%} | {e['span_tag']['precision']:.2%} / {e['span_tag']['recall']:.2%} | {v['units']} / {v['full_partition_units']} |")
    file=Path(v['file'])
    receipts[b]={'xlsx_sha256':version_contract.sha(file),'result_sha256':version_contract.sha(run/f'{b}_results.json'),'evaluation':e,'export_validation':v}
report='''# 专题一 Qwen 三集回归结果

候选版本：r24；模型：qwen3.7-flash。每集10篇，共30篇。Qwen仅收到原文、来源元数据、完整VOC字典及通用规则，未收到Codex标注答案。三个Codex参考Excel哈希保持不变。

## 已确认的验收口径

按“文章来源×标签”去重对照，标签精确率和召回率各不低于80%。关键对象错配、否定误标、结构错误、重复切片、空产品做法要求为0。参考答案差异原样计分，没有为追求一致修改Codex答案。

| 集合 | TP / FP / FN | 来源标签精确率 | 来源标签召回率 | 切片定位诊断P / R | 交付单元 / 全文分区 |
|---|---:|---:|---:|---:|---:|
'''+ '\n'.join(rows)+'''

三集均达到80%来源标签数值门槛。切片定位用字符重叠作诊断，不要求文字或边界完全一致，也不将其低分藏去。“100%”只是与本份参考答案的来源标签精确率，不代表真实业务零错误。

## 程序改进

语义分区、逐片字段生成、全323条字典检索、独立单标签核验、同片对象联合复核、局部摘要忠实性检查、身份原文核验和最终证据合同分开执行。排除围墙/外立面、地基/门楼、户内玻璃/外立面、外围水岸/社区水景等错配；现场检查建议不当已存在表现，专梯不推具体梯户比，单一房间面宽不推整户面宽，分批套数不推全盘总户数。

结构错误、重复切片及空产品做法均为0，20项程序合同单测通过。每份Excel按最新10表、35个明细字段交付，无被删除的6张工作表和10个字段；写后逐单元格读回，并独立检查各品牌、角色组的覆盖率、浓度和热度中位数。无标签片仍计入完整切片分母，热度按文章去重，不按切片重复加权。

热度优先保留合法原值，0不是缺失；仅缺值沿用两专题全量同平台、内容类型基准补算。原始互动不足时保留空并说明，不伪造0。

## 必须保留的限制

- r22首次C仅7/10运行成功；r23修复三类合同容错；r24根据C问题完善正证据合同。失败及成功缓存均保留。C已参与改进，因此最终是回归结果，不再是独立泛化验证。
- 摘要仍有ASR误转、单位补全、标题配置泄漏、确定性偏强、检查建议被交付成无标签片等残余问题。部分语义切片仍偏粗。三集通过的是当前来源标签回归门槛，不是所有字段全面生产验收。
- 含混连写数字无法安全概括时，程序保留本片原文作为摘录式做法，并记录容错；不把它称为优良摘要。
- 未手工修Qwen摘要来提升实验表现。后续若改摘要流程，三集仍须重测；批量前宜另留未参与调试的新样本做独立检查。
- 本轮只修改E盘隔离候选程序及导出适配器，未切换生产主入口，未改专题二，未写数据库或飞书，未启动300篇。

## 交付

Qwen回归集A_10篇文章.xlsx、Qwen回归集B_10篇文章.xlsx、Qwen回归集C_10篇文章.xlsx。

内部复核依据位于E盘同任务工作目录：semantic_review_AB.md、semantic_review_AB_r24.md、semantic_review_C_r24.md、frozen_version.json、run_r24各evaluation/audit/export_validation文件。后续迭代应保留本次冻结版和失败历史，不覆盖它们。
'''
(OUT/'专题一Qwen回归验收说明.md').write_text(report,encoding='utf8')
(R/'run_r24'/'final_receipt.json').write_text(json.dumps({'version':version,'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'files':receipts,'production_activated':False,'batch_300_started':False},ensure_ascii=False,indent=2),encoding='utf8')
print('Final report and three workbook hashes recorded')
