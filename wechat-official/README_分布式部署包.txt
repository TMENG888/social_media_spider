微信公众号五机分布式部署包
============================

一、用途
本包用于在五台 Windows 设备上分片执行微信公众号文章采集，并分别处理：
  专题一：文章数据、互动数据、实际评论数量，不采集评论明细；
  专题二：文章数据、互动数据、实际评论数量，以及公开页面可取得的真实评论明细。

二、便携目录
  common\src        采集、浏览器补采、清洗和合并脚本
  common\tasks      专题关键词文件（含公众号词和公开网页补充词）
  common\node_modules Playwright 依赖
  worker-01...05    每台机器独立任务队列、状态、截图、SQLite 和 runs
  manifest.json     版本和运行约定
  VERSION           包版本

三、首次配置
1. 将整个“公众号”目录复制到目标 Windows 设备，不要只复制脚本文件。
   建议放在本机普通目录（如 C:\WechatRPA\公众号），避免放入 OneDrive/网盘同步目录；SQLite 断点库和运行中间文件被同步软件占用时可能出现锁定或同步冲突。
2. 每台设备设置独立 WECHAT_WORKER_ROOT，启动对应 worker 的“启动工作节点.bat”。
   双击启动时会提示输入 MYSQL_USER 和 MYSQL_PASSWORD；主机、端口和数据库名已按 RDS 配置自动填充。密码使用 PowerShell 安全输入，不在窗口中回显，也不会写入脚本或状态文件。
3. 部署包已经内置 Node.js、Python、Chrome、Playwright、Windows 自动化和 Faster-Whisper 运行依赖，无需目标设备另行安装 Python/Node。启动脚本固定使用 common\runtime 中的便携运行时。
4. 确认 PC 微信已登录，并能打开公众号“搜一搜”文章页。程序不绕过验证码或登录限制。
5. 先执行：启动工作节点.bat check

启动 run 或 retry 时，程序会先让用户选择主显示器配置：
  1 = 2560x1440
  2 = 1920x1080
  0 = 取消运行

程序会先选择 2560x1440 或 1920x1080，再选择当前 Windows 显示缩放 100% 或 150%。程序会切换并核验分辨率、核验实际缩放比例，之后才读取数据库凭据并启动采集。如果显示器不支持所选模式、实际分辨率或缩放不匹配，任务会停止而不会盲目点击。UIA 定位优先使用实时窗口矩形；仅坐标兜底会按 100%/150% 自动换算。采集开始后，微信主窗口和搜一搜窗口会自动最大化。多显示器设备须把微信放在主显示器，且不要让窗口跨屏。

无人值守续跑可以预先设置 WECHAT_DISPLAY_PROFILE=2560x1440 或 WECHAT_DISPLAY_PROFILE=1920x1080，并设置 WECHAT_DISPLAY_SCALE_PROFILE=100 或 150，以跳过选择菜单；实际分辨率和缩放校验不会跳过。

状态库保护：每次打开 topic1/topic2 SQLite 前都会执行 PRAGMA quick_check，写入使用 DELETE journal + FULL sync，并生成一致性的 .lastgood 轮转备份。检测到 database disk image is malformed 时，原库及 sidecar 文件会先保留到 worker-xx\.state\corrupt-state\，再自动恢复 lastgood；没有可用备份时会建立新库并从“最新”顶部幂等复采。不要手工删除 corrupt-state，它用于后续审计。

关键词顺序：当前关键词只有明确到达日期截止线或确认列表耗尽后才允许进入下一关键词。partial/failed 会在原词有限重试；仍未完成就停止该 worker，下一次启动继续同一个词，不会跳过到后面的任务。单篇文章若连续三次均无法从详情页及结果卡片取得可信发布时间，会写入 SQLite 的 collection_issue 审计表并跳过该条，避免一条已删除/异常文章永久阻塞整批任务。

断点重扫去重：重启未完成关键词时仍从“最新”顶部复核，以免停机期间新增文章导致数字索引错位。不会再按标题单独跳过。只有搜索卡片的“标题+作者+发布日期”完整且在 SQLite 中唯一匹配时才不打开文章；卡片字段不完整或组合重复时，会短暂打开文章并复制稳定链接，链接已存在才快速返回，不再重复解析正文和互动数据。链接、作者或日期无法确认时按新文章完整采集。

搜一搜窗口恢复：窗口临时消失时，当前关键词最多重建 3 次，每次仍使用相同关键词并重新确认“文章/最新/顶部”。连续 3 次失败后保存断点并停止当前 worker，不继续消耗时间，也不跳到下一关键词。

深层索引定位失败：同一文章连续 3 次无法滚动到可点击区域后，不再把整个关键词卡在该索引。程序会把搜索卡片的标题、作者、发布日期、摘要特征生成指纹，写入 collection_issue，推进索引并继续后面的文章；后续重扫再次遇到同一稳定指纹会直接跳过。若连续 3 个不同文章均无法定位，则判定整个结果页面可能失效并触发熔断，避免把后续整页文章全部误判为异常并跳过。

四、运行方式
  启动工作节点.bat run       执行未完成任务，完成任务自动跳过
  启动工作节点.bat retry     重新执行失败或未完成任务
  启动工作节点.bat check     检查 Node、Python、脚本、任务文件和目录权限

每篇文章首先写入 worker 自己的 SQLite 断点库，随后导出 JSONL/CSV，再执行浏览器补采和清洗。任务之间按队列顺序运行；当前关键词出现 failed 或 partial 时会记录 task_status.json 并停止整个 worker，不会越过未完成关键词继续后面的专题或关键词。
公众号搜一搜并不保证结果严格按发布时间倒序，相关性推荐或置顶旧文可能夹在新文章之间。因此采集器不会再因遇到一篇早于截止日的文章而提前结束，而是持续遍历到结果页经过多轮滚动后确认耗尽；早于截止日的数据只过滤不保存。maxResultsPerKeyword=0 表示当前关键词不设数量上限，必须采到确认耗尽或用户安全停止后才结束。
内嵌和独立搜一搜页面均会在实际 RootWebArea 区域持续发送滚轮事件，连续8轮没有新增结果后才判定 complete_exhausted。旧版误判为 complete_exhausted 的关键词会按 wechat-pagination-v2 完成标记自动重新检查，无需删除 SQLite。
SQLite 对每篇文章逐条提交，并保存当前关键词的 next_result_index。采集器异常退出时，已提交的记录会先执行导出、清洗和入库，关键词标记为 partial，下一次 run/retry 只重试该关键词，并从“最新”列表绝对顶部重新扫描；已采链接按唯一键更新，不会重复入库。这样既不会跳到下一个关键词，也不会因顶部新增文章导致数字断点错位。若直接结束整个终端进程，操作系统可能来不及执行最后的导出动作，但已提交的 SQLite 数据仍会保留，下一次启动会重扫并最终入库。
需要人为停止时，请双击对应 worker 目录内的“安全停止当前任务.bat”，不要在运行窗口确认终止整个批处理。安全停止会等待当前文章完成，然后导出、清洗、入库已提交数据并保留断点。如果进程被强制关闭，下一次启动会在续爬之前优先恢复并入库 SQLite 中已提交的记录。

五、输出
  worker-xx\runs\topic1\ods_social_media_post_wechat_final.csv
  worker-xx\runs\topic2\ods_social_media_post_wechat_final.csv
  worker-xx\runs\topic2\ods_social_media_post_wechat_final_comments.csv
  worker-xx\runs\topic1\task_status.json
  worker-xx\runs\topic2\task_status.json

每个工作节点另有独立的按日诊断日志：
  worker-xx\logs\wechat-worker-YYYY-MM-DD.log

同一天多次 run、retry 或 check 会追加到当天同一个日志文件，不会覆盖原日志。日志包含启动时间、设备、worker、运行模式、环境检查、MySQL 预检、关键词切换、Python/Node 子进程输出、入库结果、退出码及异常堆栈；数据库密码在日志启动前读取，不会写入日志。排查跨设备问题时，请同时提供出错日期的日志、对应关键词目录下的 keyword_status.json 和 task_status.json。

六、五机合并
把五台机器的 worker-01...worker-05 目录汇总到同一目录后执行：
  node common\src\merge-workers.mjs <汇总根目录> <汇总根目录>\merged

生成统一文章表、评论表、CSV、JSONL、distributed_summary.json，以及文章/评论去重审计 JSONL。文章先按“平台+文章ID/标准链接”去重，再按清洗正文的 5 字符片段做双向相似度校验；交集除以两篇文章中较大的片段数，达到 80% 才判重，因此短摘要被长正文包含不会被误删。标题和项目不作为唯一删除依据。评论按“平台+评论ID”去重；评论ID为空时按文章+评论内容+评论时间去重。

七、任务分片
已从两份确认表提取 284 条检索词，去重后仍为 284 条。其中 276 条为公众号 PC 搜一搜可执行词，8 条为明确的 site: 公开网页补充词。公众号词已均衡分配到五台设备：worker-01/02/03 各 56 条（专题一 45、专题二 11），worker-04/05 各 54 条（专题一 44、专题二 10）。
公开网页词保存在 common\tasks\public_web_keywords.json，不会误投到公众号入口。
新增正式关键词时，只需编辑各 worker 的 task-queue.json，确保一个“专题+关键词”只分配给一台机器，然后运行：
  node common\src\validate-distributed.mjs .

八、重要限制
- 微信公众号 PC 搜一搜依赖人工登录和可用窗口；首次运行必须人工确认。
- 采集器会自动识别两类账号界面：独立 Chromium 搜一搜窗口，以及嵌入微信 Qt 主窗口的“发现 → 搜一搜”页面。实际以运行时界面结构探测结果为准，不要求用户手工选择新账号或老账号，也不按微信版本号限制启动。
- 每次识别结果会以 wechat_search_layout=detached 或 embedded 写入控制台及当日日志。环境检查仍记录微信版本用于排查，但任何版本号都不会单独阻止任务启动。
- 文章评论明细只有在公众号页面公开展开时才保存；仅显示数量而没有明细时不伪造评论行。
- ASR 需要本机 Python、faster-whisper 模型和可访问的视频资源；ASR 失败会保留空值并记录日志。
- 不要在多台机器之间复制同一浏览器登录态；每台设备使用自己的微信登录环境和状态目录。

九、云数据库入库
每个关键词完成清洗后立即入库到阿里云 RDS：
  Host: mysql.example.com
  Port: 3306
  Database: social
  Tables: ods_social_media_post、ods_social_media_comment

运行前在每台机器设置环境变量，不要把密码写入脚本：
  MYSQL_HOST=mysql.example.com
  MYSQL_PORT=3306
  MYSQL_DATABASE=social
  MYSQL_USER=数据库用户
  MYSQL_PASSWORD=
  MYSQL_ENABLED=1

MYSQL_PASSWORD 仅在实际运行环境中设置，或通过启动脚本隐藏输入；不要把真实密码写入文档、脚本或配置文件。

入库状态保存在每个关键词目录的 mysql_import_status.json。入库失败只标记当前关键词，retry 会重新入库。每批入库会先读取数据库中现有的微信公众号文章，以“平台+文章ID/标准链接+正文双向80%相似度”做全局去重，不再把项目放入文章自然键；评论自然键同样不含项目。五台机器通过 MySQL GET_LOCK 串行执行去重和入库，避免并发冲突。

十、历史重复数据清理（默认只预览，不会直接删除）
1. 在已设置 MYSQL_USER、MYSQL_PASSWORD 等环境变量的终端运行：
   node common\src\build-wechat-dedupe-map.mjs --output wechat_post_dedupe_map_values.sql
   该步骤只读数据库，使用与生产入库一致的双向80%规则生成映射 SQL。
2. 先执行生成的 wechat_post_dedupe_map_values.sql，再执行 common\sql\deduplicate_wechat_posts.sql。
3. deduplicate_wechat_posts.sql 默认 SET @apply_changes := 0，只生成并展示将保留/删除的映射。脚本只允许平台字段严格等于“微信公众号”的记录进入删除游标，并逐条复核文章链接和映射生成时的原始正文 SHA-256；任何记录缺失、平台不符或内容变化都会显示 BLOCKED，正式模式会整体拒绝删除。人工核验且安全状态为 PASS 后，把脚本顶部改为 SET @apply_changes := 1 再执行；正式模式不会再发现或加入新文章映射，只处理刚刚预览过的冻结映射。
4. 正式执行会先写入 ods_social_media_post_before_wechat_dedupe 和 ods_social_media_comment_before_wechat_dedupe，再合并更完整字段、取最大互动数、重绑评论、删除重复文章和重复评论。wechat_post_dedupe_map 与 wechat_comment_dedupe_map 永久保留审计记录。
输入数据库账号密码后，worker 会先连接 RDS，验证账号认证、social 数据库以及 ods_social_media_post、ods_social_media_comment 两张目标表。预检通过才启动微信采集；失败会立即停止，并把结果写入 worker-xx\.state\mysql_connection_check.json。
【文章栏目强校验】
程序会优先按控件文字点击“文章”，并以搜一搜页面内部标题“关键词 - 文章 - 搜一搜”复核。
若账号界面不暴露文字控件，则根据实时搜索框位置尝试兼容坐标；每次点击后仍必须通过上述复核。
无法确认时立即停止当前关键词并写入日志，不会在“全部”或“视频”栏目继续采集。

【日期截止规则】
进入文章栏目后必须成功点击“最新”；无法确认“最新”排序时立即停止，避免误用相关度排序。
在“最新”排序下，遇到第一篇早于 2026-01-01 的有日期文章时结束当前关键词，并继续下一个关键词。
如果结果在到达截止日期前已经无法继续增长，则以结果耗尽结束当前关键词。

【单篇异常不中断】
列表底部文章会先滚动到可见区域再点击。单篇文章连续三次无法打开时，本轮记录该索引并继续采集后续文章。
后续数据不会再被一篇异常文章阻断；任务结束后仍保留最早失败索引和 partial_error 状态，续跑时从最新首篇重扫并复查，链接去重保证幂等。
单次文章定位会锁定滚动方向并在接近目标时缩小步长，不会在同一次定位中上下往复滚动。
断点索引超过当前已加载数量时，会连续加载多个批次，直到该索引真实存在；不会只增长一批后访问不存在的索引。
文章链接已经出现但发布时间尚未加载时，不会把该条当作成功；程序会重新打开文章，避免静默漏掉该行。
同一文章重试时允许剪贴板链接与上次相同；只校验是否为有效微信公众号链接，不再把相同链接误判为失败。
“最新”文字控件不可见时，会以实时搜索框为锚点点击筛选位置，兼容深度滚动后的恢复页面。
单向定位因页面返回后的过期矩形而失败时，会先恢复结果页顶部，再从上向下重试，不在原位置反向振荡。
每次新检索或中断续跑都会先确认 RootWebArea 的真实垂直滚动百分比为 0.0，再把首篇定义为索引0；不能再用“第一个可见控件不移动”冒充列表顶部。
文章卡片在屏幕底部仅部分露出时，按卡片底边判断继续向下滚动，避免误判为向上而发生振荡。
微信退到托盘、主窗口暂时消失时，会优先恢复现有窗口；必要时通过环境检查发现的 WECHAT_CLIENT_PATH 唤回客户端。
若浏览器返回后控件发生一次明显DOM重排，允许且仅允许一次方向纠正；不会持续上下循环。
