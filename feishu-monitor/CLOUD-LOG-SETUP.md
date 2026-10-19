# 飞书最近24小时日志同步

群 Webhook 推送、本机归档和云文档更新分别核验。云同步只读取已确认发送的本机 report-history，不能补造历史；不因补同步重复发送群卡片。

## 部署配置

1. 将 `cloud-log-target.example.json` 复制为 `cloud-log-target.json`。填写部署方自己的 `target_url`（飞书 `/wiki/` 文档 URL）以及需要保留引用的指标文档 `metric_doc_id`。也可用进程环境变量 `FEISHU_LOG_TARGET_URL` / `FEISHU_METRIC_DOC_ID` 覆盖。真实目标配置不提交 Git。
2. 目标文档标题必须为 `飞书机器人日报日志（最近24小时）`。只替换识别为自动生成日志的正文，不改标题、其他文档或知识库设置。存在人工材料、未知块、附件或无法核验的旧模板时停止。
3. 推荐安装并自行授权官方飞书 CLI；把 `cloud-log-cli.example.json` 复制为 `cloud-log-cli.json`，填写当前机器的 `lark-cli.exe` 绝对路径，专用 profile 保持 `social-media-log`，使用 `user` 身份。授权需包含文档读取、写入及 Wiki 节点读取；原 Windows 用户的授权不能随代码复制到其他机器。
4. 不使用 CLI 时，通过 `configure-cloud-log.ps1` 隐藏输入配置文档应用凭据，并授予应用目标文档访问权。不要从浏览器抽取 Cookie，不把密钥写入目标配置或聊天。

```powershell
# 读取并核对目标和正文，不写云文档、不重发群卡片
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\sync-cloud-log.ps1 -Check

# 同步最近24小时日志，保存后重新读取核验
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\sync-cloud-log.ps1
```

必须同时满足退出码 0、`Cloud log sync confirmed` 和 `output/cloud-sync/latest-run.json` 的 `cloudConfirmed=true` 才算同步成功。CLI dry-run/保存提示不等于回读通过。

模板未配置时返回 `cloud_target_missing_or_invalid`，不会发起云文档请求。首次部署请准备能够被保护规则识别的自动日志正文；如果核查拒绝陌生内容，不要删除保护判断，应由部署方确认文档内容和导入方案。

完整历史保留本机，云端只显示最近24小时。写入前备份并核对修订版本，遇并发编辑、权限失效或部分写入结果不明时停止，保留证据供人工确认。
