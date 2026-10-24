# 地产专题混合切片与五级VOC打标程序

## 当前入口

2026-10-13批量入口新增v97全文归属补全：在成功生成之后，仅补品牌组、经营主体及项目身份，原切片、标签和摘要不变。正向核候选，反向核未补原因，显式集团简称归一，多对象与评论关系单独处理。原01至04检查点保留，身份写入独立05阶段；详见 [README_identity_completion_v97.md](README_identity_completion_v97.md)。`-FinalizeOnly`仍仅导出，不启动补标API。

2026-10-11新增全新批量生产入口 `run_bulk_v96.ps1`：两个专题各500篇文章，专题二另外附带所选文章全部956条可唯一映射的去重评论。已统一VOC-0377新业务口径——会所内有健身房即标健身房器械，无需器械清单；其他空间及泛谈仍不支持。详情见 [README_bulk_v96.md](README_bulk_v96.md)。旧样本补标入口继续保留，不可拿历史样本补标冒充新500篇运行。

2026-10-10最新生产入口仍为 `run_single_unit_v93.ps1`，现接入 v95 切片与已有标签联合补标。全文语义切片后，每一片单独遍历模型标签组、完成定义核验，再把该片原文与本轮开始时的已有标签共同扫描全部适用标签强调方向。已有标签提供对象提示，新增属性仍须有本片原文证据；明确同对象才追加，提问、否定、跨对象和历史争议转待核。新补标签不继续推导其他标签。关键词阶段不调用API、不改切片、不删旧标；评论整条处理。启动和请求隔离见 [README_single_unit_v93.md](README_single_unit_v93.md)，联合补标及复用见 [README_joint_keyword_supplement_v95.md](README_joint_keyword_supplement_v95.md)。v94/v93/v92旧输出保留作回退与同批对照，v11及初版说明均为历史流程。

当前优化实现及真实API测试使用 `delivery_v11.py` / `run_delivery_v11.ps1`，具体方法和启动方式见 [README_delivery_v11.md](README_delivery_v11.md)。一片多标签；评论整条一行；主体优先级是文章内容、文章视频内容、已有图片OCR文本。使用完整适用字典分支审核、待定候选二核、固定字典编号回填、证据编号恢复和拟排除内容反向确认。

下文保留的是历史初版说明，不代表当前v11的切片、字段或主体来源规则；不要据此启动旧版替代当前流程。当前一行是一条语义切片或完整评论，全部标签放在标签明细JSON，最终字段以README_delivery_v11及程序中的字段合同为准。

本程序把 `ods_social_media_post` 导出的 CSV 处理为两类交付数据：

- 专题一：产品信息单元表，一行对应一个项目的一条最新VOC标签路径。
- 专题二：观点信息单元表，一行对应一个项目、一个观点对象和一条最新VOC标签路径。

标签唯一来源为 `置地VOC标签体系_两专题打标版.xlsx`。原专题模板中的旧三级标签、程序中的旧补充标签均已作废，不参与召回、回退或输出。产品与观点单元统一输出一级至五级标签、标签路径ID、原编号、标签强调方向和打标说明。

## 处理顺序

1. 文章内容非空时只使用文章内容；为空时回退文章图片信息；视频文本不参与本轮切片。
2. 清洗空格、编号和标点，过滤电话、二维码、关注、私信、免责声明等营销噪声。
3. 按句末标点、编号、小标题和转折位置形成原子候选句段。
4. 专题一按标题、关键词和配置中的项目映射识别项目；专题二使用模板中的项目正式名和别名锚定项目。
5. 按最新VOC标签路径的最深层标签、强调方向和专题标签精确命中。
6. 未精确命中的句段使用本地字符 2–4 gram TF-IDF 从同专题VOC路径中补充召回，并设置更高复核要求。
7. 生成情绪方向、表达类型、创新等级、置信度及人工复核原因。
8. 为观点单元生成20至80字的独立摘要，保留原始摘录用于追溯，并执行摘要质量门控。
9. 输出产品信息单元、观点信息单元、文章处理状态和完整 JSON。

## 观点摘要规则

- `原始摘录`保存用于本单元判断的原文证据，不改写为摘要。
- `观点摘要`包含项目或评价对象以及核心事实或态度，不新增原文没有的信息。
- 摘要通常控制在20至80字；多句话只保留共同核心观点，并去除宣传修饰、重复表述、平台套话和无关背景。
- 原始摘录不超过40字且本身已经完整时，允许摘要与原文相同。
- 原始摘录超过40字且摘要仍与原文相同，自动标记`摘要待复核`并进入复核队列。
- API未返回摘要、返回摘要超过80字或引入原文没有的数字时，不能静默复制原文；程序使用保守的本地抽取式摘要，并标记`摘要待复核`。
- 本地摘要只删除噪声并抽取原文已有分句，不生成原文之外的事实。

## 安装

```powershell
python -m pip install -r requirements.txt
```

程序还需要上一级目录中的：

- `process_topic1_samples.py`：品牌、经营主体、项目、城市、产品系和做法清洗等辅助规则；其中旧三级标签规则不参与本版标签输出。
- `process_topic_samples.py`：专题二发布者角色和项目别名等辅助规则；其中旧口碑标签不参与本版标签输出。

## 运行少样本测试

```powershell
python hybrid_slice_and_label.py `
  --input "C:\Users\YS-Insight\Desktop\陈晓锋\参考数据\ods_social_media_post_all.csv" `
  --topic1-template "C:\Users\YS-Insight\Documents\WXWork\1688854558869662\Cache\File\2026-09\专题一 房地产社媒监测_V6_产品力分析数据模板.xlsx" `
  --topic2-template "C:\Users\YS-Insight\Documents\WXWork\1688854558869662\Cache\File\2026-09\专题二_北京臻澐网络及竞品口碑分析数据模板_V3.xlsx" `
  --voc-taxonomy "C:\Users\YS-Insight\Documents\WXWork\1688854558869662\Cache\File\2026-09\置地VOC标签体系_两专题打标版.xlsx" `
  --config sample_config.json `
  --output-dir output
```

## 运行50篇 API 验收测试

2026-10-08更新：`run_api_50_test.py`支持`--concurrency`，默认4并发，允许1至16；
每篇文章内候选批次仍顺序执行，每批默认6个候选，不会把4个文章并发放大为更多HTTP请求。
新增`select_per_topic_samples.py`，按项目字段精确筛选两个专题，各抽取50篇有正文或已有OCR文本的文章，
按平台、内容类型、长度和文本来源比例分层抽样。旧`select_50_samples.py`仍为两专题合计50篇，请勿混淆。
示例：`python select_per_topic_samples.py --input "ODS.csv" --base-config sample_config_50_voc5.json --output sample_config_100.json --per-topic 50`
API运行沿用下方命令，配置改为`sample_config_100.json`并追加`--concurrency 4`。
输出增加总墙钟耗时、含失败调用的已知Token/费用、未知用量调用数；未知费用不视为实际0元。
也可运行`run_two_topics_test.ps1 -PerTopic 50 -Concurrency 4`一次完成抽样、规则候选和API处理。
该启动脚本输出CSV/JSON；Excel为本次测试单独整理的验收文件。
本次新样本采用两个项目字段精确匹配，不局限原25+25篇的中海/保利与固定竞品配额。

先生成分层样本和规则候选：

```powershell
python select_50_samples.py --input "ods_social_media_post_all.csv" --output sample_config_50.json
python hybrid_slice_and_label.py `
  --input "ods_social_media_post_all.csv" `
  --topic1-template "专题一 房地产社媒监测_V6_产品力分析数据模板.xlsx" `
  --topic2-template "专题二_北京臻澐网络及竞品口碑分析数据模板_V3.xlsx" `
  --voc-taxonomy "resources\置地VOC标签体系_两专题打标版.xlsx" `
  --config sample_config_50_voc5.json `
  --output-dir output_50_voc5_rule
```

API Key 只从环境变量读取，不要写入代码、配置或命令行参数：

```powershell
$env:YS_LLM_API_KEY = Read-Host "API Key"
python run_api_50_test.py `
  --input "ods_social_media_post_all.csv" `
  --config sample_config_50_voc5.json `
  --rule-json "output_50_voc5_rule\sample_delivery_data.json" `
  --output-dir output_50_voc5_api `
  --api-base-url "http://127.0.0.1:3000" `
  --model "qwen3.7-flash" `
  --candidate-batch-size 6
Remove-Item Env:YS_LLM_API_KEY
```

模型只允许返回候选中的 `标签路径ID`，程序再从VOC字典回填一级至五级标签，从结构上阻止模型拼接或创造字典外标签。观点摘要也会执行长度、长原文原样复制和新增数字校验。实测发现每批12个候选仍可能触发输出 JSON 截断，因此生产默认建议每批不超过6个候选。程序设置 `enable_thinking=false`，以减少延迟和无关推理 Token。

API 明细会记录输入 Token、缓存命中 Token、输出 Token、总 Token、响应时间、重试、计价模式、单价、网关费用和本地计算费用。

默认采用用户于 2026-09-30 提供的 Qwen3.7-Flash 实时 API（单次输入不超过 32K Token）价格：普通输入 ¥0.2/百万 Token、缓存输入 ¥0.04/百万 Token、输出 ¥0.8/百万 Token。也可选择 `batch_file` 或 `batch_chat`，当前默认价格均为输入 ¥0.1、输出 ¥0.4/百万 Token。价格来源：<https://www.qianwenai.com/models/qwen3.7-flash#context>。平台价格可能调整，正式结算以账单为准。

通过参数选择模式或覆盖单价：

```powershell
--pricing-mode realtime
--input-price-per-million 0.2 `
--cached-input-price-per-million 0.04 `
--output-price-per-million 0.8
```

费用公式：`(输入Token-缓存命中Token)/1,000,000×输入单价 + 缓存命中Token/1,000,000×缓存输入单价 + 输出Token/1,000,000×输出单价`。如果接口直接返回费用，结果中同时保留接口费用和本地估算，计费费用优先采用接口返回值。

## 运行全量

复制一份配置文件，把 `sample_ids` 改为空数组。正式全量处理前应完成：

- 确认专题二最终三个项目及正式别名。
- 对 200–300 篇分层样本做盲审并校准阈值。
- 将多项目比较、隐含态度、反问和低相似度单元送人工或大模型复核。
- 把项目字典、标签字典和规则版本纳入版本控制。

## 输出文件

- `产品信息单元.csv`
- `观点信息单元.csv`
- `文章处理状态.csv`
- `sample_delivery_data.json`

每次运行会校验所有输出的标签路径ID及一级至五级值是否与最新VOC字典完全一致；发现旧标签、错层级或跨专题标签时直接终止，不生成伪成功结果。专题一使用VOC文件中标记为专题一的产品路径；专题二使用文件中标记为专题二的路径，并强制将所有一级标签为“客户”的行纳入专题二。

脚本只读输入文件，不执行数据库 `INSERT`、`UPDATE` 或 `DELETE`。
