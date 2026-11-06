# 飞书登录与验证运维机器人

监听已配置的运维群，把小红书、抖音既有登录会话的二维码和人工验证状态发到群内，并接收人工 @ 指令。`feishu-monitor` 继续负责进度日报；两者使用独立群配置。此目录不启动爬虫，不领取任务，不提供任意远程命令执行。

## 行为

- 需要扫码、短信或人工验证时发橙色卡片；登录与原检索权限核验通过后发一次绿色卡片。取得实际续采证据后编辑原成功消息；抖音还要求内容入库证据。
- 自动批次按 work01 → work02 → work03 → work04，同机小红书先于抖音。每机独立读取线程；超时机器不会无限阻塞当前可用批次，人工指令直接响应。
- 示例配置为每 30 分钟提醒仍需处理的节点；状态观察保持每 8 秒。只有等待扫码／过期二维码阶段可定时刷新，扫码确认、短信与验证码过程中不刷新。
- 短信首次发送必须取得对应平台请求的成功响应。静态“已发送”文案、倒计时或按钮点击都不算平台受理证据；平台受理不保证手机实际收到。定时提醒不重发短信。
- 二维码必须能本地解码，并通过会话、阶段、截图时间与文件摘要核验；不返回或记录解码内容。取消后编辑原二维码卡片移除图片。
- 人工停止、有效冷却和安全保护保持；只操作目标机器、平台的已有登录会话。多个候选会话时要求补充 worker 编号，不能猜测。

## 部署

需要 Windows、Python 3.10+、Node.js 18+ 和已完成 bot 身份授权的飞书 CLI。CLI 需支持代码中的 `event consume`、消息发送／编辑与图片上传命令；事件订阅必须包含 `im.message.receive_v1`，机器人需加入目标群。使用知识库功能时另行配置相应读取权限。

```powershell
python -m pip install -r requirements.txt
npm ci --omit=dev
Copy-Item config.example.json config.json
```

编辑本机 `config.json`：填写 CLI 可执行文件、profile、运维群 ID、应用 ID、bot open ID，以及四台机器的共享根目录。根目录下需有 `小红书/worker-XX/.state/login-bridge`、`抖音/worker-XX/.state/login-bridge`。共享权限与浏览器所属用户的本机维护权限需在部署时配置，本程序不授予权限。无对应机器可从 `machine_roots` 删除条目。

`runtime_dir`、`login_cache_dir` 和 `secret_file` 使用可写的绝对路径；示例放在 E 盘。`LOGIN_BRIDGE_NODE` 可指定 Node 完整路径，未设置则从 PATH 查找。`bot_mention` 是消息中的人工操作提示。`machine_accounts` 默认留空；如需显示身份，仅在私有配置填写机器的 `phone`、`platforms` 下各平台 `nickname`，不要提交账号映射。

此入口保留原机器人普通对话／知识库功能，启动时仍要求配置模型地址、模型名和 Windows DPAPI 密钥；它们不是登录指令解析的依赖。知识库和群上下文在示例中关闭。密钥经交互隐藏输入保存，只能由同一 Windows 用户解密：

```powershell
python -B bot.py setup-secret --config config.json
python -B bot.py run --config config.json
```

后台控制：`./control.ps1 -Action Start -Python <python.exe完整路径>`；`Stop` 写入优雅退出请求，`Status` 读取本机状态。默认不安装定时任务；需要时显式调用 `InstallStartup` 并提供可用的 `-PythonWindowless`。源码更新后不会自动部署到集群。

## 群内指令

```text
@机器人 登录状态 work03 小红书
@机器人 刷新登录 work03 小红书
@机器人 登录截图 work03 小红书
@机器人 重发验证码 work03 抖音
@机器人 验证码 work03 抖音 <手机收到的数字>
```

短信重发每条人工指令仅尝试一次，至少间隔 60 秒。验证码在进入模型、SQLite 和普通群历史存储前拦截，以 RSA-OAEP 绑定机器、平台、worker、登录会话和挑战 ID 后传输；群内用户原始消息仍受飞书自己的保留策略管理。

## 离线验证

```powershell
python -B tests/run_offline.py
npm ci
node qr-validation/validate-qr.test.cjs
```

Python 回归拒绝套接字连接和子进程启动，覆盖通知去重、新群路由、顺序、超时、30 分钟提醒、二维码失效清图、停止授权及验证码保密。二维码解码测试仅生成无账号意义的合成图片。`LOGIN_TEST_TEMP` 可指定测试目录，默认 E 盘。

两平台目录还提供 `common/sms-login.browser.test.mjs`，通过 Playwright 拦截所有测试页面和短信接口，以本地合成页面验证发送、受理、失败、加密绑定和重放限制。先安装各平台依赖及浏览器，按需设置 `LOGIN_TEST_CHROME`，再运行 `node sms-login.browser.test.mjs`。`node recovery-expired-security.test.mjs` 检查已过期自动冷却与仍有效保护的边界，不连接 Redis。

发布前这些离线验证通过；既有 work03／work04 实网验证仅确认短信请求获平台成功响应，不代表手机送达及完整人工登录流程已经全部验收。
