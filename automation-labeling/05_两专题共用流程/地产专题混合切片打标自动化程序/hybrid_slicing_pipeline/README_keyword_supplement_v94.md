# 关键词兜底补标

生产入口 `run_single_unit_v93.ps1` 已接入。顺序：全文语义切片 → 单片分组模型查漏 → 定义、证据及冲突核验 → 关键词兜底 → 导出产品、观点两表。评论不拆，关键词不决定边界。

兜底阶段遍历专题一323、专题二580条适用字典中的所有标签强调方向。程序从真实路径提取空间对象和属性：例如“会所功能·游泳池”对应“会所 + 游泳池/泳池”；“空调”的路径要求厨房，所以还必须出现厨房。只在同一个原句内匹配，保存原始字符位置；不能跨评论发言者、跨切片或借父文章属性。

明确的产品配置和有数值的对应尺度/数量可以直接补入。中文数字、繁体字及少量明确同义词支持匹配。反问、否定、条件、跨对象、历史明确否决、客户本人身份/服务阶段/宽泛语义等需要判断的候选转人工待核，不依赖共现硬补。规划/宣传等事实的原有限定保留，不能改写为实际交付。

只处理当前交付主表，新增标签按路径ID片内去重，由原字典回填八键JSON。旧标签、切片原文、项目、摘要、情绪、文章评论映射和指数保持；不自动恢复被排除/待核的单元。不会为了消除重复而跨不同事实删标签。本地规则追加不产生API请求、Token或费用，之前的模型用量不重复计算。

已有两表的结果JSON可以只做本地兜底，不重发前面的模型请求。完整本地补标、测试和导出入口：

```powershell
.\run_keyword_supplement_v94.ps1 -InputResult '上轮目录/delivery_results.json' -OutputDir '新版本目录'
```

底层处理命令：

```powershell
python keyword_supplement_v94.py --input '上轮目录/delivery_results.json' --taxonomy '真实标签体系.xlsx' --output-dir '新版本目录'
python token_cost_report_v93.py --output-dir '新版本目录'
python package_two_workbooks_v87.py --input '新版本目录/delivery_results.json' --prior '上轮目录/delivery_results.json' --taxonomy '真实标签体系.xlsx' --output-dir '新版本目录'
```

之后用既有 Artifact Tool 导出器导出两张Excel并运行 `verify_supplement_delivery_v92.py`。字典和原CSV不修改。关键词命中、直接补入、待核原因在既有“标签补选与纠错”页；覆盖数量在“补选覆盖记录”页。没有人工金标准时不能报告总体漏标率或宣称零漏标。
