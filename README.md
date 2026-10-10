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

## 使用边界

仅采集公开或已获授权的内容。遇到登录、验证码、频控、权限或付费边界时停止任务并由人工处理，不绕过平台限制。

