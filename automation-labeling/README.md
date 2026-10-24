# 自动化打标源码

本目录同步截至 2026-10-24 的本机程序。保留中文目录和版本化模块，方便对应原有运行入口；这是**源码备份与发布，不是自带业务数据、模型、凭据的便携包**。

## 当前入口

| 目录 | 程序与范围 |
| --- | --- |
| `01_广告打标/数据库程序` | `label_ads.mjs`：北京臻澐项目口碑、仅补空白“是否广告”，严格是/否；`--self-test` 不访问数据库/API。实际 `--run` 会写库，必须核实目标。缓存恢复工具需原始审计文件，不可直接用于新批次。 |
| `01_广告打标/少样本评估` | 广告识别小样本、参考对照及压力测试，不能当作全库验收。 |
| `02_发布者角色打标` | 角色判断、抽样对照、参考复核及工作簿导出；不是独立的全库写回服务。 |
| `03_专题一_产品信息单元` | 专题一产品做法切片和标签处理。 |
| `04_专题二_观点信息单元` | 当前 `topic2_pipeline_v108.py`，沿用 v107/v106 的项目归属、切片评分及汇总；`slice_sentiment_v107.py` 使用原本地 FP32 RoBERTa，不用父文分数或 Qwen 数值替代。 |
| `05_两专题共用流程` | `hybrid_slicing_pipeline/run_bulk_v96.ps1` 批量流程与 v97 身份补全；保留语义切片、全字典补标、证据校验、并发治理及历史兼容版本。 |
| `06_专题一_当前Qwen流程` | 当前 r49 语义切片、全字典裁决和证据校验，以及 500 篇专门批次的有界修复/范围保护；保留冻结合同约束，不发布业务输入和实际冻结清单。 |
| `support` | 当前专题二链路原先放在外部工作目录的评论项目归属与 v99/v101 公共源码依赖。 |

## 依赖和配置

- Python 3.11+。公共工程的 `requirements.txt` 列出 openpyxl、numpy、scikit-learn、requests。RoBERTa 推理另需 transformers、onnxruntime 与经过原程序来源校验的模型文件；模型不上传，也不自动下载。
- Node.js 22.13+。广告程序默认复用仓库 `xiaohongshu/common` 的 MySQL 依赖，先在该目录 `npm ci`；可通过 `SPIDER_COMMON_ROOT` 指定其他公共目录。
- 模型 API 密钥仅从 `YS_LLM_API_KEY`、原程序支持的其他密钥变量/安全输入获取。发布副本将内网网关替换为本地示例；公共 Python 入口使用 `--api-base-url`，广告/角色 Node 程序支持 `LLM_API_BASE_URL`。不要将示例地址当作已部署服务。
- MySQL 使用爬虫的 `MYSQL_HOST/PORT/DATABASE/USER/PASSWORD` 配置。仓库不保存真实云数据库地址、密码或加密缓存。
- 专题二当前链路：`LABEL_PROJECT_FILE` 指向获批的 `projects.json`，`LABEL_TAXONOMY_FILE` 指向同批 `taxonomy.json`（默认与项目文件同目录）。未提供项目清单时明确报错，不能偷偷借用原机数据。项目 ID、标签 ID 与历史证据必须一致。
- `LABEL_WORK_DIR`、`LABEL_OUTPUT_DIR`、`LABEL_SOURCE_INVENTORY` 指定工作目录、产出目录和已有来源清单；默认新文件使用 E 盘。先调用当前入口的 `configure(output_dir)`，再使用其 runner/处理/导出接口。
- `LABEL_SENTIMENT_MODEL`、`LABEL_SENTIMENT_PYTHON` 指定本地模型和推理 Python；`LABEL_NODE`、`LABEL_NODE_MODULES` 可指定专题二导出运行时。Excel 导出依赖 `@oai/artifact-tool`，不随仓库发布。
- 公共工程 `resources` 中的 XLSX 是标签字典源码资产，不是文章或评论数据。`sample_config.example.json` 只给结构，需填自己的合法样本与项目设置。

历史评估/修复脚本仍有原环境的文件路径、固定样本及输入约束，保留它们用于复查既有链路，不代表在新电脑上可直接双击运行。历史数据派生的 `d_reference_v80.json` 和 `independent_label_anchors_v59.json` 不发布；相关评估须自行提供获批参考，空白 example 不是金标准。运行前检查所有输入、输出、数据库目标及收费 API 调用；不要批量执行目录里的 `run_*` 或所有测试。部分测试需要未发布的历史数据，不能据此声称已全量验收。

## 不含业务数据的检查

在仓库根目录，先安装上述 Node 依赖；以下广告自检只验证保护逻辑，不写库、不调用模型：

```powershell
$env:AD_LABEL_OUTPUT='E:\Codex\work\ad-label-self-test'
node 'automation-labeling/01_广告打标/数据库程序/label_ads.mjs' --self-test
python -B -m unittest discover -s automation-labeling/tests -v
```

本次仅运行离线合约/Mock 回归，没有新发起收费打标、重写历史标签、改动生产库或提交人工作为金标准。源文切片、标签证据、广告准入和角色判断仍是不同环节，单元测试通过不等于语义效果或内容覆盖率已验收。
