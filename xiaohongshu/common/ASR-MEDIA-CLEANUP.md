# ASR成功媒体自动清理（2026-10-13）

## 已实施规则

抖音、小红书生产代码均已接入：
1. 工作节点启动时，遍历本机任务断点，清理历史已完成媒体。
2. 每个ASR任务完成时，检查后清理本篇媒体。
3. 删除失败仅记警告，保留文件，下次启动重试；不将完成的字幕任务改为失败。
4. `asrKeepMedia=true` 可明确禁用自动清理；生产默认使用 `false`。

## 什么时候可以删除

必须同时满足：
- ASR任务和文章断点均为completed；
- 任务字幕、文章视频内容、识别审计相互一致，已在SQLite事务中可靠保存；
- 识别审计为ok，字幕不触发过短、丢失分段、已知幻觉或质量拒绝规则；
- 或确实为已记录的无语音/静音/无音轨；
- 所有引用该文件的本地任务都符合以上条件；
- 文件位于该任务专属media/asr-media目录内，是普通媒体文件，非链接、目录或多重硬链接。

保留pending、running、retry_pending、dead_letter、需质量复核、记录损坏、不一致、来源不明的媒体。不会按文件年龄批量删，也不会删除断点库、字幕JSON、ASR模型、文章或评论。

成功的依据是本地事务，不冒充MySQL已提交。MySQL回填失败时，本地字幕与审计仍保留，可从断点再次入库，不需重新识别音频。删除原媒体后，若要人工听视频复核，需要重新下载，旧媒体链接不保证永久有效。

## 更新其他机器

这是基于当前生产部署包的增量，不能直接覆盖到缺少近期修复模块的旧版本。

安全停止节点，等待收尾；备份即将替换的代码，然后覆盖本更新包的两个平台common/src文件。不要覆盖.state、runs、登录状态、Redis或MySQL凭据。

抖音额外将common/config.json中的一个字段改为：
```json
"asrKeepMedia": false
```
只改此字段，保留机器上的其他配置。为避免覆盖机器配置，本增量压缩包不包含完整config.json。本机该设置已经完成。

小红书现有设置就是false，不需改动。重启后新功能生效；已运行进程不会热更新。不需要重新设置Redis任务。

## 替换文件

两个平台均为：
- common/src/asr-jobs.mjs
- common/src/asr-media-cleanup.mjs（新增）
- common/src/cleanup-worker-asr-media.mjs（新增）
- common/src/run-worker.mjs

抖音另有：
- common/src/collector.mjs
- common/config.json中asrKeepMedia字段（手动合并，不包含在压缩包中）

## 手工预览/清理

使用部署包自带的Node，默认仅预览，无需数据库密码、Redis密码或网站登录。
```powershell
# 在抖音common目录运行
.\runtime\node\node.exe .\src\cleanup-worker-asr-media.mjs --state-root ..\worker-01\.state --media-name media
# 小红书common目录运行
.\runtime\node\node.exe .\src\cleanup-worker-asr-media.mjs --state-root ..\worker-01\.state --media-name asr-media
```
核对后加`--apply`执行删除，删除不经过回收站。只删满足校验的媒体，不更改任务状态。
