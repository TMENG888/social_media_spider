# Social Media Spider

面向多平台公开内容采集的 Playwright/RPA 源码集合。

## 平台目录

- `baidu-news`：百度资讯网页采集
- `douyin`：抖音分布式采集
- `wechat-official`：微信公众号桌面端采集
- `wechat-channels`：微信视频号桌面端采集
- `xiaohongshu`：小红书 Playwright 采集

## 仓库范围

仓库只保存程序源码、测试、依赖清单、配置示例和操作文档。以下内容不纳入版本控制：

- Node/Python/浏览器运行时及 ASR 模型
- `node_modules`
- 采集任务队列和 worker 分片
- 登录态、运行状态、SQLite 断点、日志和采集结果
- Redis/MySQL 密码及本机网络配置
- 可分发 ZIP 包和其他大型二进制文件
- 临时验收记录、历史修复说明和一次性生产数据修复脚本

平台目录只保留当前有效版本，不在源码仓库中长期保留按日期命名的补丁包或迁移快照；历史变更由 Git 提交记录追踪。

## 基本使用

各平台是相对独立的程序。进入对应目录后，根据其 `README`、`package.json`、`requirements*.txt` 和启动脚本安装依赖、配置任务。

Node 项目通常执行：

```powershell
npm install
```

需要 Redis 的平台，将 `redis-config.example.json` 复制为 `redis-config.json`，再填写实际地址和用户名。密码通过环境变量或隐藏输入提供，不写入配置文件。

需要 MySQL 的平台，设置以下环境变量：

```text
MYSQL_HOST
MYSQL_PORT
MYSQL_DATABASE
MYSQL_USER
MYSQL_PASSWORD
```

## 2026-10-15 本机源码同步

本次同步包含小红书、抖音、视频号的重试/补采验收、有界重试与无变化处置、远程安全停止、心跳及已验证产出遥测，并补充跨平台飞书监控与本地日报归档。百度资讯、公众号按本机现有源码同步；生产连接默认值统一改为本机示例，不附带生产环境配置。

- [飞书监控、配置与远程停止说明](wechat-channels/feishu-monitor/README.md)
- [本次同步范围与验证边界](SOURCE_SYNC.md)

这是**源码更新，不是开箱即用的完整便携部署包**。自行准备运行时、ASR 模型、浏览器、worker 目录、任务清单及凭据。Node.js 建议 22.13+，Python 建议 3.11+；小红书/抖音在各自 `common` 安装依赖，视频号/公众号同样在 `common` 执行 `npm ci` 并安装 Python 依赖。

本次未执行真实平台采集、生产任务验收或飞书推送，未更改运行节点及调度。完成、含跳过完成、未解决跳过必须分开统计；不得将无变化处置描述为成功采集或质量合格。各平台旧部署说明/manifest 中的任务数量、批次和历史实测描述仅是原部署记录，不是本次环境配置或验收结果。

## 使用边界

仅采集公开或已获授权的内容。遇到登录、验证码、频控、权限或付费边界时停止任务并由人工处理，不绕过平台限制。

