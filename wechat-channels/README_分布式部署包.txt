微信视频号三机分布式采集部署包
版本：2026.10.01-channels-resilience.25-search-db-asr

一、采集范围

1. 专题一：223 个检索词，只采帖子，不采评论明细。
2. 专题二：53 个检索词，采帖子及页面公开可见评论。
3. 日期：2026-01-01 至执行当天。
4. 只采集 PC 微信“搜一搜 > 视频 > 最新”实际返回的公开或已获授权内容。
5. 不绕过登录、验证码、访问频控、权限或平台安全机制。

二、三台机器分配

worker-01：专题一 75 词，专题二 18 词，共 93 词。
worker-02：专题一 74 词，专题二 18 词，共 92 词。
worker-03：专题一 74 词，专题二 17 词，共 91 词。

每个词只分给一台机器。每台机器先完成专题一，再执行专题二。
静态模式中 partial/failed 会保留待重试状态，但本轮继续其他关键词；下次启动精准复核异常视频。
Redis 模式中一个任务对应一个“专题 + 关键词”，失败任务不确认，其他机器仍可领取后续任务。

三、字段映射（保持原 ODS 表结构）

视频号点赞 -> 文章点赞数
视频号推荐（心形） -> 文章收藏数
视频号转发 -> 文章分享数
视频号评论总数 -> 文章评论数
文章内容 -> 固定为空（视频号按本项目口径不写视频文案）
视频字幕/语音转写 -> 文章视频内容
视频号作者 -> 作者名字
视频号分享链接 -> 文章链接
finder id 优先；无 finder id 时使用“标题+作者+发布时间+时长”复合键 -> 文章id
公开评论 -> ods_social_media_comment 原字段
平台固定为“微信视频号”，内容类型固定为“视频”。

已有云数据库若仍包含 utf8mb3 文本列，可按维护窗口执行
common\sql\upgrade_existing_ods_to_utf8mb4.sql。升级前，入库器会自动识别旧列并仅对
这些列移除无法存储的四字节字符，防止单个 emoji 导致整批事务回滚。

页面没有公开显示的数值保持 NULL，不把“按钮存在”写成 0。公开视频号预览页通常不暴露播放量；因此播放量不伪造，也不挤占现有互动字段。推荐数沿用原公众号约定写入“文章收藏数”。

四、部署

1. 将完整“视频号”目录复制到每台 Windows 机器。不能只复制 worker-0N，因为启动器依赖同级 common 中的运行环境、代码、任务表和 ASR 模型。
2. 三台机器分别运行 worker-01、worker-02、worker-03 中对应的启动器；其他 worker 目录可保留，无需删除，也不会被当前启动器调用。
3. 每台机器人工登录 PC 微信，完成可能出现的扫码或验证码。
4. 分辨率使用 2560x1440 或 1920x1080，Windows 缩放支持 100% 或 150%。
5. 配置 MYSQL_USER、MYSQL_PASSWORD；如只做本地测试，设置 MYSQL_ENABLED=0。
6. “启动工作节点.bat”和“启动两阶段采集.bat”现在都执行同一个一体化流程。数据库密码只输入一次。
   每条新视频首次打开详情时同时采集元数据、互动量、专题二评论和完整音频；录音结束即写检查点并关闭详情，RPA继续下一条。
   分享页或缓存存在完整媒体时直接离线处理；否则按 WeChatAppEx.exe 进程回环录音。每台机器的常驻 Faster-Whisper large-v3 服务异步转写并回填“文章视频内容”。
7. 需要停机时双击“安全停止当前任务.bat”，不要结束进程或删除 .state。

五、可选 Redis 动态调度（三台机器利用率更高）

1. 静态 worker-01/02/03 分片仍然保留；Redis 模式与静态模式二选一，同一轮不要混跑。
2. 在同一局域网的一台稳定主机部署 Redis 6.2+，设置访问密码并只向可信局域网开放 6379。三台采集机无需安装 redis-cli 或 Python 第三方包。
3. 三台机器分别双击“启动Redis动态工作节点.bat”。Redis URL 和 REDIS_RUN_ID 已由启动器统一设置，Redis 密码会从各 worker 的“.credentials\redis-password.txt”自动加载，不再重复输入（当前正式任务为 20260926-prod-01）。该凭据文件为便携式明文配置，只能随对应 worker 部署包交付给受信任设备，禁止上传、截图或对外发送。
4. 调度粒度为“专题 + 单个检索词”。Redis Streams consumer group 保证健康机器不会同时领取同一任务。
5. 任务执行期间每 30 秒续租；连续 3 次心跳失败会先安全停止当前任务。机器断电、微信异常退出或网络中断后，租约静默 300 秒即可由其他机器 XAUTOCLAIM 回收。
6. 三台worker默认均为mixed，可并行领取不同关键词；每次重启会优先回收至多1个租约已过期的主任务pending，之后继续未读关键词，并公平检查精准视频补采。仍可通过REDIS_WORKER_ROLE=primary/mixed/asr手工覆盖角色。
7. 同一个 REDIS_RUN_ID 重启不会重复播种；需要全新重跑时更换 REDIS_RUN_ID，不要直接删除 Redis 全库。
8. REDIS.env.example 给出了变量示例。URL 中不要写密码，密码在启动时掩码输入。
9. 各节点继续保留 worker-0N\logs 下的本机按日日志，同时把脱敏后的任务事件与子进程输出写入 wechat:channels:<RUN_ID>:logs。任务分发机双击根目录“启动集中日志接收.bat”，即可持续落盘到 central-logs\<RUN_ID>\<日期>，同时生成 all.log/all.jsonl 和按消费者拆分的日志。Redis日志流默认近似保留20万条，集中接收端用原子游标断点续收；日志失败不影响爬虫任务。

六、断点、去重与入库

1. 每个 worker、每个专题使用独立 SQLite；Redis 模式额外同步每条视频的指纹、完整记录、评论、字段完成度、重试状态和死信状态。
2. 不设每关键词数量上限（maxResultsPerKeyword=0）。
3. 一个关键词每轮只扫描一次，不再立即从头重跑 5 轮。重新运行时仍从顶部识别新视频，但已完成卡片只核对指纹，不再打开详情页；仅异常/新增视频进入详情采集。
4. 单条视频本轮只尝试 1 次；跨运行累计失败不足 3 次进入 retry_pending，第 3 次失败进入 video_dead_letter，并输出 channels_video_dead_letter.csv/jsonl。
5. retry_pending/completed_metadata 会进入独立 video-retry 流，不再把已完成年度扫描的整个关键词留在主 pending；补采消费者按视频指纹复核，达到上限后进入死信表供人工复核。
6. 同一专题内不同关键词命中相同 finder/share 文章ID时保留首次记录，后续命中跳过评论和ASR；两个专题的项目口径不同，允许各保留一条业务记录。
7. finder id 优先作为 article_key；无 finder id 时使用标题、作者、发布时间和时长复合键，不再只凭标题合并。
8. ASR 工作写入 asr_job 持久表。进程重启时可继续处理仍存在的音频；跨机器接管时若音频仅在故障机器本地，则按视频指纹重新捕获。
9. MySQL 使用字段级非空合并；新一轮 NULL 不覆盖数据库中已有有效值。整批入库仍在事务中执行。
10. 状态 JSON、JSONL、CSV 和浏览器补充结果均使用临时文件完成后原子替换。
11. 主关键词存在未解决子视频时状态为completed_with_deferred_retries；存在死信时为completed_with_dead_letters。只有全部子视频达到终态且无死信，父关键词才最终标记completed。

七、文件

common/src/channels_pc_collector.py：PC 微信搜一搜视频采集、断点、导出。
common/src/channels_resilience.py：Redis 视频级跨机器检查点和原子文件写入。
common/src/atomic-file.mjs：Node 侧状态及最终结果原子写入。
common/src/channels_browser_enricher.mjs：视频号公开预览页补充文案、作者、日期和互动数。
common/src/channels_ods_postprocess.mjs：字段清洗与 ODS 输出。
common/src/mysql-import.mjs：原表结构 MySQL 幂等入库。
common/src/redis_task_queue.py：Redis Streams 播种、领取、心跳、异常回收与成功确认。
common/src/redis_log_sink.py：任务分发机集中接收Redis日志并按日期、消费者落盘。
common/run-redis-worker.ps1：Redis 动态节点入口，一次输入环境配置后持续领任务。
common/build-three-worker-shards.py：从两份任务 JSON 重建三机分片。
根目录“生产部署文件清单.txt”：跨机器复制范围、必需文件和可清理目录说明。
根目录“生产运行操作流程.txt”：Redis 三机启动、领取、断点、重试、死信和停机流程。

八、已知平台边界

1. PC 微信或账号 UI 改版后，可能需要调整 common/collector_config.json 的视频栏目回退坐标。
2. 能解析到媒体流或字幕轨时，不需要完整播放视频；可直接下载后离线 ASR。若公开视频号预览页只提供封面和元数据、不提供真实媒体流，才需要在已登录 PC 微信中按实际时长播放并按微信音频进程录音。录音前先做3秒有效波形预检；预检通过才完整播放，避免整条播放后才发现静音。
3. 评论面板为虚拟列表，只保存页面公开且实际加载到的评论；评论总数与抓到的评论明细数分别处理。
4. 登录失效、验证码或风控必须人工处理，然后原地重启 worker。

九、生产包验收命令

环境：common\check-env.ps1
三机分片：node common\validate-distributed.mjs <视频号目录>
Python 语法：common\runtime\python\python.exe -m py_compile common\src\channels_pc_collector.py common\src\redis_task_queue.py
采集器入口：common\runtime\python\python.exe common\src\channels_pc_collector.py -h
Redis 队列入口：common\runtime\python\python.exe common\src\redis_task_queue.py -h

十、生产目录与测试归档

1. 生产目录不再携带 common\tests、live-*、two-stage-smoke-* 等测试代码和测试结果。
2. 历史测试产物已移动到与“视频号”同级的“视频号_测试归档_20260924_1845”，需要时可恢复，不参与生产运行。
3. worker-0N 下的 .state、logs、runs 是运行时目录；新包中可以为空，正式运行后会自动产生断点、日志和结果，不能在续爬期间删除。
【2026-10-01 一体化采集与非阻塞双队列】
Redis主任务在视频首次详情访问时完成元数据、互动量、专题二评论与完整音频采集；录音结束即写检查点，常驻ASR服务异步转写并回填。三台worker默认全部mixed，按“主关键词→检查精准补采”公平轮转。video-retry只接收静音、录音不完整、定位失败、ASR失败或质量不合格的视频；消费者可在没有本地SQLite的机器上从Redis恢复目标行，只水合、导出并打开当前视频指纹，不会增加同关键词其他视频的失败次数。只有主任务流与补采流的pending和lag都为0时，节点才会显示队列完成。

2026-09-30修复：精准ASR任务只处理当前article_key/fingerprint，不再重导出整个关键词，也不再连带老化其他retry_pending视频；无标题、作者、文章ID或链接的占位指纹不会消耗重试预算。10秒以上视频统一执行字幕完整性复核，最低密度为0.65字/秒。真实微信验证已完成52秒进程回环录音、large-v3转写、SQLite回填及详情窗口关闭。

2026-09-30空结果断点：无论本地是否已有文章，关键词首次显示明确“无结果”都只写入partial_empty_unverified/partial_inconsistent_empty异常断点，不再判定完成，也不允许Redis XACK。当前运行可继续处理其他关键词；后续运行会跳过正常complete_*关键词，并从顶部重新采集这些异常断点。旧版complete_explicit_empty断点也会自动重新打开复核。

2026-09-30访问节奏：生产配置启用随机抖动——提交关键词前5～12秒、搜索加载4～8秒、滚动加载1.8～4秒、详情打开前3～7秒、返回列表2～5秒、关键词切换20～50秒；每处理8～15条视频随机长休息30～90秒。Redis动态模式另外使用原子Lua令牌，使同一Run ID三台机器提交/重建搜一搜关键词的时点至少随机间隔12～25秒。令牌不限制已打开详情页、视频播放、ASR、清洗、导出和MySQL入库；Redis令牌不可用时默认停止新搜索而不是失控放行。

Redis任务被重置后会生成新的中央generation。worker按“Run ID + generation”自动使用独立的 .state\redis-runs 和 runs\redis-runs 目录；旧机器上历史SQLite和keyword_status不会参与新一轮采集，也不会造成新任务被误跳过。

搜索页面若0张卡片但没有微信明确的“暂无/未找到相关结果”提示，将记录partial_result_surface_empty并保留Redis任务，不再误记complete_exhausted。每条详情采集成功或失败后都会校验详情窗已关闭、搜索页可用；关闭失败会停止继续打开新窗口，避免窗口线性叠加。

【2026-09-29 实机搜索入口与矛盾空结果保护】
新账号全局搜索使用“回到聊天列表 -> 输入关键词 -> 向下选择首个建议 -> Enter”打开完整搜一搜页面，兼容100%/150%缩放。若微信在已有本地文章或视频断点时突然显示“暂无相关结果”，任务记为partial_inconsistent_empty并保留待重试，不会误记完成或确认Redis主任务。

【2026-09-30 精准补采修复】
mixed节点领取video-retry后只做一次有上限的目标卡片扫描：近期任务默认36张，深层任务按原索引向后预留36张，硬上限240张；找不到时记录partial_retry_target_not_found并保留Redis任务，不再重建同一关键词页面三轮。仅比对卡片期间不触发“每8～15条视频休息30～90秒”，真正提交搜索、滚动、打开详情和返回列表仍保留随机抖动。调度器会把已解析的REDIS_URL、REDIS_PASSWORD与REDIS_RUN_ID显式传给补采子进程，跨机器SQLite为空时仍能从正确命名空间水合单条视频。精准导出同时使用keyword与article_key时不再发生SQLite参数数量错误。

音频回采优先使用Windows音频会话中的WeChatAppEx PID；视频暂停使音频会话暂时消失时，回退使用当前视频详情窗口所属PID继续进程级回采，不再盲目退回全系统端点。视频时长以详情播放器“已播/总时长”的总时长为准，避免把搜索卡片的自动播放剩余时长误当完整时长而截断字幕。实机已分别验证worker-02与worker-03完成Redis领取、精准定位、微信进程录音、Faster-Whisper回填、completed终态及redis_video_retry_acked。

【2026-09-30 有界旧任务恢复与集中日志】
主扫描节点重启后不再永久绕过旧pending：若旧任务租约已静默超过REDIS_RECLAIM_IDLE_SECONDS（默认300秒），本次进程优先XAUTOCLAIM至多1个旧关键词；处理一次后继续未采集的新关键词，避免同一异常关键词循环霸占节点。每台机器的任务开始、领取、子进程逐行输出和结束码同步进入当前Run ID的有界Redis日志流，密码写入前脱敏；任务分发机通过“启动集中日志接收.bat”断点接收并生成可检索JSONL和人工可读LOG。

【2026-09-30 安全停止同步】
worker-01/02/03的“安全停止当前任务.bat”统一改为在同目录原子替换带请求时间、worker编号和来源的stop.requested。主扫描或ASR补采会完成当前视频，持久化SQLite/Redis检查点、导出并入库，然后停止外层Redis节点且不再领取下一项；收到停止标记、当前任务收尾和节点停止事件会进入集中日志。任务分发机上的集中日志接收器不随采集worker停止，以便收完最后日志。
