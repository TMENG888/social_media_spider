import json
from pathlib import Path
p=Path(r'D:/Codex/outputs/01a1349d-c76e-7b63-be36-3c8e0766deef/20261013_各平台广告盲测50条/pressure_10_16_20')
d=json.loads((p/'pressure_results.json').read_text(encoding='utf-8'))
rows=json.loads((p/'all_results.json').read_text(encoding='utf-8'))
assert d['complete'] and len(rows)==300 and d['total_attempts']==300
assert len({(r['tier'],r['round'],r['sample_id']) for r in rows})==300
assert all(len(r['attempts'])==1 and r['attempts'][0]['http_status']==200 and r['label_valid'] for r in rows)
for s in d['stages']:
 assert len([r for r in rows if r['tier']==s['tier']])==100
text=['# Qwen广告识别并发压力测试','', '## 结论','', '10、16、20路均通过两轮短批次测试。本轮最高测试并发为20，尚未测出网关真实极限。20路相比10路短批次吞吐提升约87%，平均完成50条耗时从13.53秒降至7.23秒。','', '建议先使用16路作为日常起点，保留429/超时自动降并发、重试与请求速率限制。20路可以作为短批次候选，不能据此认定长时间或长文本生产稳定。未修改生产核心或默认配置。','', '## 逐档结果','', '| 并发 | 调用数 | 接口及标签JSON成功率 | 每50条平均秒 | 短批次条/分钟 | P95响应秒 | 429/超时/重试 | 与明确Codex基准一致 | 全部引用逐字通过 |','|---|---:|---:|---:|---:|---:|---|---:|---:|']
for s in d['stages']:
 text.append(f"| {s['tier']} | {s['rows']} | {s['success']/s['rows']:.1%} | {s['wall_seconds']/2:.2f} | {s['throughput_rows_per_min']:.1f} | {s['p95_seconds']:.2f} | 0/0/0 | {s['reference_agree']}/{s['reference_definite_n']}（{s['reference_agree']/s['reference_definite_n']:.1%}） | {s['evidence_exact_rows']}/100 |")
text+=['','## 测试边界与质量','', '使用此前冻结的5平台各10条样本，每档重复两轮。所有请求实际发出HTTP，不复用本地响应缓存。模型qwen3.7-flash，temperature=0.1，enable_thinking=false，输出上限8192，HTTP绝对超时90秒，单条最多2次尝试，总尝试上限500。本轮实际300次，全部首尝试成功。测试护栏为滚动300RPM、保守估算350万TPM、最多20个实际HTTP在途。','', '短批次吞吐可暂时超过300条/分钟，不代表长期可按这个速度运行。在保留300RPM护栏时，持续请求吞吐上限仍受300RPM约束，重试也占额度。这个护栏不是已核实的账户官方额度。','', '每档只有100条短测且重复同一组数据；档位顺序为10→16→20，可能受预热、网关负载及服务端前缀缓存影响，不是随机顺序控制实验。没有验证网关是否存在额外响应缓存。不能用重复样本短测推断全量长期容量。','', 'Codex明确基准每轮45条，5条待判断不进入二分类一致率分母。基准为Codex独立预判，不是人工金标准。20路与原Qwen基线标签一致96/100，但与明确Codex基准一致80/90。10、16、20路与基准一致率分别87.8%、88.9%、88.9%，未观察到随升并发明显下降，样本量不足以证明没有质量变化。','', '全部证据逐字校验通过率仅41%、46%、47%。省略拼接、改写或空引用会判未通过，即使其中部分证据确实可追溯。接口100%返回成功不等于100%可自动验收，需继续规范证据引用。','', '## Token与费用','',f"输入Token合计：{sum(s['prompt_tokens'] for s in d['stages']):,}。输出Token合计：{sum(s['completion_tokens'] for s in d['stages']):,}。总Token：{sum(s['total_tokens'] for s in d['stages']):,}。",'',f"配置价格估算费用：{sum(s['estimated_yuan'] for s in d['stages']):.6f}元。未知usage尝试：{sum(s['unknown_usage_attempts'] for s in d['stages'])}。该金额沿用原程序输入0.20、缓存0.04、输出0.80元/百万Token配置，不是网关账单。服务端缓存可能降低估算费用。",'', f"总测试墙钟耗时：{d['elapsed_seconds']:.2f}秒。各档均已验证实际HTTP在途峰值分别达到10、16、20。",'', '原始响应及逐次HTTP/usage账本保留在本报告同目录。未知usage为0仅指本轮，不能外推到历史任务。']
(p/'Qwen广告并发压力测试报告.md').write_text('\n'.join(text),encoding='utf-8')
print('Verified 300 unique runs, HTTP ledger and completed tiers; report saved.')
