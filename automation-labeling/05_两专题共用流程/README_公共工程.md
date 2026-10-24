# 两专题公共工程

这里保留原工程目录结构：上层的两个process_topic模块、字典，以及下层hybrid_slicing_pipeline。源码、测试、README和原配置按原文件字节复制，保留历史版本以避免当前核心的导入依赖断裂。

排除所有test_results目录、node_modules链接、__pycache__、日志、生成缓存、模型响应及运行检查点。配置和根目录的小型JSON固定测试样例一并保留，不包含全量CSV源数据。

主要入口：

- run_bulk_v96.ps1 / run_bulk_v96.py：两专题批量流程，PowerShell入口接入v97身份补全。
- resume_missing_v96.py / resume_limited_v96.py：原检查点恢复；不是普通新任务入口，未经确认不要启动第二个恢复进程。
- run_single_unit_v93.ps1：既有成功结果上的单片全字典/关键词补标流程。
- apply_identity_completion_v97.py：品牌、经营主体、项目全文归属补全。
- luna_review_gateway_v98.py：现有Luna代理评审客户端；只是保留代码，不代表本次验证了网关可用性。
- export_two_workbooks_v87.mjs / verify_bulk_v96.py：双工作簿导出和核验。

保留原resources中的VOC字典，并在工程根目录另放同一份字典供查找，哈希相同。原脚本中的机器绝对路径没有自动重写。调用前显式指定输入、输出和字典；输出不要指向本代码目录，不要覆盖或移走已有批次缓存。

本次没有执行生产入口、恢复入口、导出入口或外部API；复制/语法核验不等于新机器部署验收，也不等于标注质量验收。
