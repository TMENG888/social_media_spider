# 跨平台飞书采集监控

采样端只读当前配置的 Redis 任务池与 MySQL 汇总，输出本地看板及四区块飞书卡片：进度、机器状态、质量效率、异常下一步。不要将队列完成等同于成功采齐、内容非空率等同于准确率，或租约等同于机器心跳。

飞书关键词进度仅展示“完成✅ / 重试 / 待领”三项：完成为队列终态合计（含策略跳过结案，但扣除明确仍待入库的任务），不等于逐条采齐；重试为执行中、重试、补采、重采、失败待处理及明确待入库任务的合并展示；待领为确认尚未尝试的新任务。未知状态或缺少尝试证据时显示“未确认”，不靠相减虚构状态。此映射仅用于摘要，不改任何 Redis 状态。旧快照缺少完整队列分布时不推测细分数值。飞书不展示历史停止节点记录，记录和原始状态仍保留在本机看板。

飞书“④ 异常与下一步”仅列实际已进入待重试/重采状态的关键词任务（视频号还包括已进入延后补采的关键词），不把执行中租约、仍待入库标记或未重入重试的独立 failed 状态当作已进入重试。死信、待审核、核心字段缺失等历史诊断不在群日报异常区展示，但仍保留在本机看板的诊断清单；不因此修改、跳过或确认任何业务任务。没有观察到待重试任务不表示内容质量已通过审核。独立实时故障告警链路不受日报展示过滤影响。

机器状态新增“当前执行新任务 / 重试”分组，指已领取且正在执行的任务，不是进度区的待领库存。视频号根据当前注册心跳及同一 consumer 的任务记录/重采策略判断，不能把 `primary` 队列简单认作新任务；小红书/抖音只读有效租约的当前尝试次数（领取时已加一，所以首次为 1，重试大于 1），运行中的重采策略优先归为重试。缺少证据显示“类型未确认”，过期租约不计当前工作。平台租约类型按任务汇总，与心跳在线统计独立；仅有 worker 槽位号时不强行映射到某台电脑，不要求远程节点重启或同步新增采集器文件。

统一入口现在位于仓库/部署包根目录的 `feishu-monitor`，与小红书、抖音、视频号同级，不再隶属于视频号。三个平台的原启动入口、任务状态、凭据和浏览器登录目录保持独立，采集器不需要监控进程才能运行。监控只复用现有视频号的 Node/Python 运行时及 Redis 读取模块，不启动采集器；不需要复制运行时或重新登录。

## 配置与运行

1. 仓库布局在 `../wechat-channels/common` 准备 Node/Python 依赖；中文便携部署包自动定位 `../视频号/common/runtime`。也可使用自行安装的 Windows PowerShell、Python 3.11+、Node.js 22.13+；依赖安装不由监控自动触发。
2. 将 `config.example.json` 复制为 `config.json`，填写任务批次、项目范围、任务清单位置和凭据文件路径。`platform_directories` 默认对应仓库英文目录；中文部署包需改为实际中文目录。
3. 为小红书/抖音自行准备 `common/redis-config.json`、`common/tasks/redis-tasks.json`，使其与真实生产池一致。仓库不附带任务清单、worker 状态或凭据；不能仅凭示例配置查询原生产环境。
4. 通过 `configure-bot.ps1` 的本机隐藏输入配置已有群机器人的 Webhook 与签名，凭据仅以 Windows 用户/机器绑定方式保存在 `.credentials`。不要提交到 Git，也不要把密钥发到聊天中。

```powershell
# 只读采样与本地预览，不推送
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run-once.ps1

# 采样并推送一次（会向配置的飞书群发送消息）
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run-once.ps1 -Send
```

`-Send -Watch` 是单次运行的变化检测与进度限频模式，不是常驻循环。机器/数据源变化触发推送，进度变化至少间隔 15 分钟，无变化不推送。`run-once.ps1` 不会自行创建定时任务；需要定时时由部署方显式安装下述 Windows 任务。

小红书/抖音采样使用各自 `worker-01/.state/redis-password.dpapi`；视频号与 MySQL 凭据路径由配置指定。已有凭据仅能由其原 Windows 用户在原机器解密。MySQL 也支持进程环境变量 `MYSQL_HOST`、`MYSQL_PORT`、`MYSQL_USER`、`MYSQL_PASSWORD`，默认连接示例是本机，不是生产服务。

## Windows 定时日报（不依赖 Codex）

可显式安装 Windows 任务 `SocialMedia-Feishu-Daily-09-14-18`，每天北京时间 09:00、14:00、18:00 运行一次，不依赖 Codex。源码检出不会安装任务，也不会变更任何已有调度；迁移时由部署方自行停用重复日报。

```powershell
# 显式安装或更新本机专用任务；必须使用保存现有加密凭据的 Windows 用户。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install-scheduled-report.ps1

# 查询 Windows 任务运行结果及下次时间（不会推送）
Get-ScheduledTaskInfo -TaskName 'SocialMedia-Feishu-Daily-09-14-18'

# 停用本机 Windows 定时推送（不会停止采集器）
Disable-ScheduledTask -TaskName 'SocialMedia-Feishu-Daily-09-14-18'
```

任务使用当前用户的交互登录身份，电脑需开机、联网且该用户已登录；可关闭 Codex、可锁屏，但注销或睡眠期间无法准点发送，恢复可运行状态后补跑。安装程序要求系统时区为北京时间，不修改系统时区、执行策略、休眠或电源设置。不保存 Windows 登录密码，不使用无法读取用户加密凭据的替代账户。

运行入口为 `run-scheduled-report.ps1`，后台调用原 `run-once.ps1 -Send`，只有进程退出码为 0、收到飞书确认、回读到本次实际归档且云日志同步核验通过时才记整体成功。`output/scheduler/latest-run.json` 为最近结果，同目录按运行 ID 保留历史；不落盘原始进程输出或凭据。Windows 设置为不重叠执行、失败不自动重发，避免发送已成功而归档或云同步失败时重复发卡片。失败请分别核对 `deliveryConfirmed`、`archiveConfirmed`、`cloudConfirmed` 和 `childExitCode`。`-Preview` 可只验证采样和预览，不发送群消息，也不调用云文档。

## 送达与归档

必须同时检查进程退出码和 `Feishu delivery confirmed`；失败不能声称送达。成功推送后保存 `output/report-history` 逐条记录，并生成最近 24 小时的 `recent-day-reports.md` 和 `cloud-log-body.txt`。缺失历史不会补造。

已接入独立云文档同步：`run-once.ps1 -Send` 在推送归档后调用 `sync-cloud-log.ps1`，只更新指定日志文档正文，重新读取核验后才记 `cloudConfirmed=true`。请按 [CLOUD-LOG-SETUP.md](CLOUD-LOG-SETUP.md) 配置部署方自己的目标文档及官方 CLI 授权。仓库不包含任何团队文档标识，示例目标未配置时明确失败，不会尝试写入默认文档。`run-scheduled-report.ps1` 分别记录群送达、本机归档、云同步，云失败仍保留前两项真实结果且整体退出码非零。只补云同步可单独运行 `sync-cloud-log.ps1`，不重复发群卡片。群消息送达始终不代表云文档更新成功。

## Redis 远程安全停止

群 Webhook 只负责推送，**不能在飞书群里直接输入停止指令**。本仓库提供独立的 Redis 安全停止入口，必须先在目标节点加载新版代码。

```powershell
# 只查状态
.\remote-control.ps1 -Platform xhs -Action status

# 预览指定节点的停止请求，不写 Redis
.\remote-control.ps1 -Platform xhs -Action stop -Computer EXAMPLE-PC -Worker worker-01 -DryRun

# 经确认后请求安全停止；将示例主机名替换为目标机器真实 hostname
.\remote-control.ps1 -Platform xhs -Action stop -Computer EXAMPLE-PC -Worker worker-01 -ConfirmTarget 'EXAMPLE-PC/worker-01'
```

抖音使用 `-Platform douyin`。查询回执确认收到和安全收尾，不能仅凭发出请求判定进程已退出。`release` 还需最新状态中的 `-CommandId`，只解除对应远程停止标记，不启动爬虫。不要用于未经授权的机器；此入口与只读采样是不同操作。

视频号使用 `../wechat-channels/common/control-redis-worker.ps1`（中文包为 `../视频号/common/control-redis-worker.ps1`），通过 `Get-Help` 核对其独立参数；不要混用平台控制键。

## 告警监听

`run-incident-relay.ps1 -Check` 仅检查三平台连接和监控待发送条目数量，不发送消息、不改任务。正常 `run-incident-relay.ps1` 沿用现有发送回执，不因迁移重发历史告警。新的监听支持通过本目录 `output/incident-relay.stop` 安全退出；重新运行前由操作人确认并移走该停止文件。不会创建计划任务或开机启动项。

## 数据库回读异常监控

视频号数量验收回读链路现在记录脱敏错误码及 connect/query/validation/runtime 阶段，并写入对应 worker 的 `.state/database-readback-status.json` 和 `database-readback-events.jsonl`。实际目标地址、端口、库名、配置来源、是否本机回环均可本机核对，不记录账号、密码、SQL 或原始驱动报错。

首次故障/故障类型变化经新增监控专用键入既有告警待发队列；同故障去重，真正的数据库回读成功后才报告恢复。Redis 不可用时保留 `.state/database-monitor-outbox.json`，下一次回读观测时补报，不代表此时已送达飞书。普通策略快照校验成功不能证明数据库恢复。它不读取其他机器的日志文件；远程节点必须加载配套补丁才会上报。

`视频号/common/check-database-readback.ps1` 是单独的只读检测入口：复用已有本机凭据或隐藏输入，检查数据库与目标表权限，不连接 Redis、不领取任务、不发送群卡片、不自动改地址或重启进程。此监控增强本身不修复历史启动入口的数据库地址配置。

## 离线测试

群卡片机器状态按平台去重：同一 worker 编号存在心跳正常、机器归属明确的节点时，不再展示该编号的历史心跳过期、无注册心跳或已停止记录。同一编号在多台机器同时在线，仍按各真实机器及执行节点分别统计；未被正常心跳替代的失联节点继续提示。冷却/休眠节点也属于在线遥测。该规则仅影响通知展示及视频号机器状态变化判断，不删除 Redis 记录、不改变任务或租约统计；本机快照和证据看板保留历史。

```powershell
python -m unittest discover -s . -p 'test_*.py' -q
```

测试使用假 Redis、数据库样本和临时目录，不发送飞书消息。跨机器统计仅覆盖已加载对应遥测代码的节点；没有收到遥测不证明没有实际产出。
