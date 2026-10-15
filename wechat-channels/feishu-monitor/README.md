# 跨平台飞书采集监控

采样端只读当前配置的 Redis 任务池与 MySQL 汇总，输出本地看板及四区块飞书卡片：进度、机器状态、质量效率、异常下一步。不要将队列完成等同于成功采齐、内容非空率等同于准确率，或租约等同于机器心跳。

## 配置与运行

1. 在 `../common` 执行 `npm ci --ignore-scripts`，安装 `requirements.txt` 中的 Python 依赖；准备 Windows PowerShell、Python 3.11+、Node.js 22.13+。保留原便携部署布局时，也可以使用自行准备的 `common/runtime`。
2. 将 `config.example.json` 复制为 `config.json`，填写任务批次、项目范围、任务清单位置和凭据文件路径。`platform_directories` 默认对应仓库英文目录；中文部署包需改为实际中文目录。
3. 为小红书/抖音自行准备 `common/redis-config.json`、`common/tasks/redis-tasks.json`，使其与真实生产池一致。仓库不附带任务清单、worker 状态或凭据；不能仅凭示例配置查询原生产环境。
4. 通过 `configure-bot.ps1` 的本机隐藏输入配置已有群机器人的 Webhook 与签名，凭据仅以 Windows 用户/机器绑定方式保存在 `.credentials`。不要提交到 Git，也不要把密钥发到聊天中。

```powershell
# 只读采样与本地预览，不推送
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run-once.ps1

# 采样并推送一次（会向配置的飞书群发送消息）
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run-once.ps1 -Send
```

`-Send -Watch` 是单次运行的变化检测与进度限频模式，不是常驻循环。机器/数据源变化触发推送，进度变化至少间隔 15 分钟，无变化不推送。脚本不会创建定时任务，本次源码发布也不恢复任何旧调度。

小红书/抖音采样使用各自 `worker-01/.state/redis-password.dpapi`；视频号与 MySQL 凭据路径由配置指定。已有凭据仅能由其原 Windows 用户在原机器解密。MySQL 也支持进程环境变量 `MYSQL_HOST`、`MYSQL_PORT`、`MYSQL_USER`、`MYSQL_PASSWORD`，默认连接示例是本机，不是生产服务。

## 送达与归档

必须同时检查进程退出码和 `Feishu delivery confirmed`；失败不能声称送达。成功推送后保存 `output/report-history` 逐条记录，并生成最近 24 小时的 `recent-day-reports.md` 和 `cloud-log-body.txt`。缺失历史不会补造。云文档写入不在此脚本中自动完成，需另行授权、同步并刷新回读；群消息送达不代表云文档更新成功。

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

视频号使用 `../common/control-redis-worker.ps1`，通过 `Get-Help` 核对其独立参数；不要混用平台控制键。

## 离线测试

```powershell
python -m unittest discover -s . -p 'test_*.py' -q
```

测试使用假 Redis、数据库样本和临时目录，不发送飞书消息。跨机器统计仅覆盖已加载对应遥测代码的节点；没有收到遥测不证明没有实际产出。
