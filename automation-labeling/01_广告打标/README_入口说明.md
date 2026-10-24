# 广告打标

## 数据库程序

`数据库程序/label_ads.mjs`为原广告打标程序；`start_secure.ps1`负责隐藏输入数据库密码，`start_restore_secure.ps1`及其配套脚本用于既有缓存恢复。完整规则、失败处理及更新约束见数据库程序/README.md。

生产目标仍是 `social.ods_social_media_post` 的北京臻澐项目口碑，且仅更新空值“是否广告”。不因代码被归档就获得扩大项目、覆盖已有值或恢复数据库的授权。本次未启动任何数据库操作。

原程序导入外部小红书worker依赖：

`C:/Users/YS-Insight/Desktop/爬虫任务/专题一/Playwright百度资讯RPA/分布式部署包/小红书/common`

没有复制该worker的连接配置或凭据，也没有改变它。默认输出路径与原缓存位置保持不变。

## 少样本评估

`少样本评估/prepare.py`、`reference.py`、`qwen_test.py`、`assemble.py`、`build.mjs`为此前抽样与对照代码；`pressure_test.py`、`pressure_report.py`为此前受控并发测试代码，不是普通打标入口。

少样本是三分类“广告/非广告/待判断”，数据库回写是二分类“是/否”。reference.py包含固定样本人工式判定规则；不能拿来自动评审任意新样本。qwen_test.py和pressure_test.py仍通过原绝对路径导入delivery_v4；该模块副本也保存在05公共工程。

所有历史输出路径均原样保留；执行前确认不会覆盖旧样本、缓存或参考。数据库程序只从当前进程MYSQL_USER、MYSQL_PASSWORD及YS_LLM_API_KEY读取凭据，不在本目录保存凭据。
