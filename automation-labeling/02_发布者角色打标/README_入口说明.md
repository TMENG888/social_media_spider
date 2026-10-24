# 发布者角色打标

现有代码是两个专题各50条的少样本测试与全文复测，不是已实现的全库数据库回写任务。

## 代码职责

- `role_sample_prepare.py`：分平台抽样，保存原文/输入包；默认全文复测模式，依赖原冻结样本，拒绝覆盖已有冻结参考。
- `role_qwen.mjs`：角色模型识别入口；4路并发、最多3次尝试、逐字证据验证、请求输入审计、签名缓存复用；401/403不继续该条重试。`--full-text`会核对输入与原始字段一致性。
- `role_reference.py`、`role_full_reference.py`：此前特定样本的Codex参考与全文修订，不能当任意新数据的自动金标准。
- `role_review_packet.py`、`role_full_review.py`：辅助阅读评审输入。
- `role_normalize.py`：保留原响应并做约定范围的角色名称归一。
- `role_compare.py`、`role_build.mjs`、`role_verify.py`：对照统计、Excel生成与保存结果核验。

四分类为：品牌、区域公司、项目官方；媒体及专业机构；普通账号；身份不明。判断的是发布账号，不是文章描述的品牌或项目；广告与发布者角色是两个独立维度。

## 路径与依赖

模型入口从YS_LLM_API_KEY读取原Qwen网关密钥，不包含凭据。Qwen调用地址与模型配置在role_qwen.mjs中保留原值；本次没有切换模型。

默认历史结果根目录：

`D:/Codex/outputs/01a1349d-c76e-7b63-be36-3c8e0766deef/20261014_发布者角色各50条盲测`

全文复测目录为上面目录加“_全文复测”。部分模型/对照入口可通过ROLE_TEST_OUTPUT指定路径，其他准备和参考脚本仍保留原绝对路径，不能假定一个环境变量会重定向整套流程。本次没有复制历史数据，也没有运行这些脚本。

role_build.mjs需要Codex现有artifact-tool Node运行环境；Python核验依赖openpyxl。对新样本需要另做准备、冻结与独立参考，不要复用旧参考冒充独立准确率。
