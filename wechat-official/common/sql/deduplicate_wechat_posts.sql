/*
  微信公众号历史数据安全去重（MySQL 8.0.36）

  使用前：
  1) 先运行 build-wechat-dedupe-map.mjs，生成并执行 wechat_post_dedupe_map_values.sql，
     才会包含“不同链接、正文双向相似度 >= 80%”的近似重复映射。
  2) 本文件默认 @apply_changes=0，只生成确定性映射并展示预览。
  3) 确认预览后把下一行改成 SET @apply_changes := 1; 再执行本文件。

  保留规则：最早文章发布时间 -> 最早获取时间 -> 最小 id。
  合并规则：互动数取最大值，空字段补齐，正文/标签/媒体字段取更完整值；
            文章图片信息强制为空；评论重绑至保留文章后再去重。
*/
SET NAMES utf8mb4;
SET @apply_changes := 0;

CREATE TABLE IF NOT EXISTS `wechat_post_dedupe_map` (
  `duplicate_id` BIGINT NOT NULL,
  `survivor_id` BIGINT NOT NULL,
  `reason` VARCHAR(32) NOT NULL,
  `similarity` DECIMAL(9,6) NOT NULL,
  `duplicate_url` LONGTEXT NULL,
  `survivor_url` LONGTEXT NULL,
  `duplicate_body_sha256` CHAR(64) NULL,
  `survivor_body_sha256` CHAR(64) NULL,
  `duplicate_keyword` VARCHAR(100) NULL,
  `duplicate_project` LONGTEXT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `status` VARCHAR(20) NOT NULL DEFAULT 'pending',
  `applied_at` DATETIME NULL,
  PRIMARY KEY (`duplicate_id`),
  KEY `idx_wechat_dedupe_survivor` (`survivor_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

SET @has_duplicate_body_hash := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='wechat_post_dedupe_map' AND COLUMN_NAME='duplicate_body_sha256'
);
SET @dedupe_ddl := IF(@has_duplicate_body_hash=0,
  'ALTER TABLE `wechat_post_dedupe_map` ADD COLUMN `duplicate_body_sha256` CHAR(64) NULL AFTER `survivor_url`',
  'SELECT 1');
PREPARE dedupe_stmt FROM @dedupe_ddl; EXECUTE dedupe_stmt; DEALLOCATE PREPARE dedupe_stmt;
SET @has_survivor_body_hash := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='wechat_post_dedupe_map' AND COLUMN_NAME='survivor_body_sha256'
);
SET @dedupe_ddl := IF(@has_survivor_body_hash=0,
  'ALTER TABLE `wechat_post_dedupe_map` ADD COLUMN `survivor_body_sha256` CHAR(64) NULL AFTER `duplicate_body_sha256`',
  'SELECT 1');
PREPARE dedupe_stmt FROM @dedupe_ddl; EXECUTE dedupe_stmt; DEALLOCATE PREPARE dedupe_stmt;

CREATE TABLE IF NOT EXISTS `wechat_comment_dedupe_map` (
  `duplicate_id` BIGINT NOT NULL,
  `survivor_id` BIGINT NOT NULL,
  `reason` VARCHAR(32) NOT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `status` VARCHAR(20) NOT NULL DEFAULT 'pending',
  `applied_at` DATETIME NULL,
  PRIMARY KEY (`duplicate_id`),
  KEY `idx_wechat_comment_dedupe_survivor` (`survivor_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

DELIMITER $$
DROP PROCEDURE IF EXISTS `run_wechat_post_dedupe`$$
CREATE PROCEDURE `run_wechat_post_dedupe`(IN do_apply TINYINT)
main: BEGIN
  DECLARE lock_acquired INT DEFAULT 0;
  DECLARE done INT DEFAULT 0;
  DECLARE invalid_map_count INT DEFAULT 0;
  DECLARE duplicate_id_value BIGINT;
  DECLARE survivor_id_value BIGINT;

  DECLARE post_cursor CURSOR FOR
    SELECT m.`duplicate_id`, m.`survivor_id`
    FROM `wechat_post_dedupe_map` m
    JOIN `ods_social_media_post` d ON d.`id`=m.`duplicate_id`
    JOIN `ods_social_media_post` s ON s.`id`=m.`survivor_id`
    WHERE m.`status`='pending' AND m.`duplicate_id`<>m.`survivor_id`
      AND d.`平台`='微信公众号' AND s.`平台`='微信公众号'
      AND d.`文章链接` <=> m.`duplicate_url`
      AND s.`文章链接` <=> m.`survivor_url`
      AND m.`duplicate_body_sha256` IS NOT NULL
      AND m.`survivor_body_sha256` IS NOT NULL
      AND SHA2(COALESCE(d.`文章内容`,''),256)=m.`duplicate_body_sha256`
      AND SHA2(COALESCE(s.`文章内容`,''),256)=m.`survivor_body_sha256`
    ORDER BY m.`survivor_id`, m.`duplicate_id`;

  DECLARE comment_cursor CURSOR FOR
    SELECT m.`duplicate_id`, m.`survivor_id`
    FROM `wechat_comment_dedupe_map` m
    JOIN `ods_social_media_comment` d ON d.`id`=m.`duplicate_id`
    JOIN `ods_social_media_comment` s ON s.`id`=m.`survivor_id`
    WHERE m.`status`='pending' AND m.`duplicate_id`<>m.`survivor_id`
      AND d.`平台`='微信公众号' AND s.`平台`='微信公众号'
    ORDER BY m.`survivor_id`, m.`duplicate_id`;

  DECLARE CONTINUE HANDLER FOR NOT FOUND SET done=1;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    DO RELEASE_LOCK('wechat_ods_import');
    RESIGNAL;
  END;

  SELECT GET_LOCK('wechat_ods_import', 60) INTO lock_acquired;
  IF lock_acquired <> 1 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='无法取得 wechat_ods_import 锁；请先停止公众号入库进程';
  END IF;

  /* 只有预览模式生成新映射；正式模式只使用人工刚刚审核过的冻结映射。 */
  IF do_apply <> 1 THEN
  /* 确定性规则一：同平台+文章id；文章id为空时同平台+标准链接。 */
  DROP TEMPORARY TABLE IF EXISTS `tmp_wechat_post_natural_rank`;
  CREATE TEMPORARY TABLE `tmp_wechat_post_natural_rank` AS
  SELECT q.*,
         ROW_NUMBER() OVER (
           PARTITION BY q.`natural_key`
           ORDER BY q.`published_at`, q.`acquired_at`, q.`id`
         ) AS `rn`
  FROM (
    SELECT p.`id`, p.`文章链接`, p.`关键词`, p.`项目`,
      CASE
        WHEN NULLIF(TRIM(p.`文章id`),'') IS NOT NULL
          THEN CONCAT(TRIM(p.`平台`),'|id|',TRIM(p.`文章id`))
        WHEN NULLIF(TRIM(p.`文章链接`),'') IS NOT NULL
          THEN CONCAT(TRIM(p.`平台`),'|url|',
            CASE
              WHEN TRIM(p.`文章链接`) REGEXP '^https?://mp\\.weixin\\.qq\\.com/s/[^/?#]+'
                THEN LOWER(TRIM(TRAILING '/' FROM SUBSTRING_INDEX(TRIM(p.`文章链接`),'?',1)))
              ELSE LOWER(TRIM(TRAILING '/' FROM TRIM(p.`文章链接`)))
            END)
        ELSE NULL
      END AS `natural_key`,
      COALESCE(STR_TO_DATE(REPLACE(LEFT(p.`文章时间地点`,19),'T',' '),'%Y-%m-%d %H:%i:%s'),
               STR_TO_DATE(LEFT(p.`文章时间地点`,10),'%Y-%m-%d'),
               CAST('9999-12-31 23:59:59' AS DATETIME)) AS `published_at`,
      COALESCE(p.`文章获取时间`,CAST('9999-12-31 23:59:59' AS DATETIME)) AS `acquired_at`
    FROM `ods_social_media_post` p
    WHERE p.`平台`='微信公众号'
      AND NOT EXISTS (SELECT 1 FROM `wechat_post_dedupe_map` x WHERE x.`duplicate_id`=p.`id`)
  ) q
  WHERE q.`natural_key` IS NOT NULL;

  INSERT IGNORE INTO `wechat_post_dedupe_map`
    (`duplicate_id`,`survivor_id`,`reason`,`similarity`,`duplicate_url`,`survivor_url`,`duplicate_body_sha256`,`survivor_body_sha256`,`duplicate_keyword`,`duplicate_project`)
  SELECT d.`id`, s.`id`,
         IF(d.`natural_key` LIKE '%|id|%','article_id','article_url'),
         1.000000, d.`文章链接`, s.`文章链接`,
         SHA2(COALESCE(dp.`文章内容`,''),256),SHA2(COALESCE(sp.`文章内容`,''),256),d.`关键词`, d.`项目`
  FROM `tmp_wechat_post_natural_rank` d
  JOIN `tmp_wechat_post_natural_rank` s ON s.`natural_key`=d.`natural_key` AND s.`rn`=1
  JOIN `ods_social_media_post` dp ON dp.`id`=d.`id`
  JOIN `ods_social_media_post` sp ON sp.`id`=s.`id`
  WHERE d.`rn`>1 AND d.`id`<>s.`id`;

  /* 确定性规则二：清洗后的非空正文完全相同。80%近似映射由 Node 脚本生成。 */
  DROP TEMPORARY TABLE IF EXISTS `tmp_wechat_post_body_rank`;
  CREATE TEMPORARY TABLE `tmp_wechat_post_body_rank` AS
  SELECT q.*,
         ROW_NUMBER() OVER (
           PARTITION BY q.`body_key`
           ORDER BY q.`published_at`, q.`acquired_at`, q.`id`
         ) AS `rn`
  FROM (
    SELECT p.`id`, p.`文章链接`, p.`关键词`, p.`项目`,
      SHA2(REGEXP_REPLACE(LOWER(p.`文章内容`),'[[:space:][:punct:]]+',''),256) AS `body_key`,
      COALESCE(STR_TO_DATE(REPLACE(LEFT(p.`文章时间地点`,19),'T',' '),'%Y-%m-%d %H:%i:%s'),
               STR_TO_DATE(LEFT(p.`文章时间地点`,10),'%Y-%m-%d'),
               CAST('9999-12-31 23:59:59' AS DATETIME)) AS `published_at`,
      COALESCE(p.`文章获取时间`,CAST('9999-12-31 23:59:59' AS DATETIME)) AS `acquired_at`
    FROM `ods_social_media_post` p
    WHERE p.`平台`='微信公众号'
      AND NULLIF(REGEXP_REPLACE(LOWER(COALESCE(p.`文章内容`,'')),'[[:space:][:punct:]]+',''),'') IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM `wechat_post_dedupe_map` x WHERE x.`duplicate_id`=p.`id`)
  ) q;

  INSERT IGNORE INTO `wechat_post_dedupe_map`
    (`duplicate_id`,`survivor_id`,`reason`,`similarity`,`duplicate_url`,`survivor_url`,`duplicate_body_sha256`,`survivor_body_sha256`,`duplicate_keyword`,`duplicate_project`)
  SELECT d.`id`, s.`id`, 'body_exact', 1.000000,
         d.`文章链接`, s.`文章链接`,
         SHA2(COALESCE(dp.`文章内容`,''),256),SHA2(COALESCE(sp.`文章内容`,''),256),d.`关键词`, d.`项目`
  FROM `tmp_wechat_post_body_rank` d
  JOIN `tmp_wechat_post_body_rank` s ON s.`body_key`=d.`body_key` AND s.`rn`=1
  JOIN `ods_social_media_post` dp ON dp.`id`=d.`id`
  JOIN `ods_social_media_post` sp ON sp.`id`=s.`id`
  WHERE d.`rn`>1 AND d.`id`<>s.`id`;
  END IF;

  SELECT COUNT(*) INTO invalid_map_count
  FROM `wechat_post_dedupe_map` m
  LEFT JOIN `ods_social_media_post` d ON d.`id`=m.`duplicate_id`
  LEFT JOIN `ods_social_media_post` s ON s.`id`=m.`survivor_id`
  WHERE m.`status`='pending'
    AND (
      m.`duplicate_id`=m.`survivor_id`
      OR d.`id` IS NULL OR s.`id` IS NULL
      OR d.`平台`<>'微信公众号' OR s.`平台`<>'微信公众号'
      OR d.`平台` IS NULL OR s.`平台` IS NULL
      OR NOT (d.`文章链接` <=> m.`duplicate_url`)
      OR NOT (s.`文章链接` <=> m.`survivor_url`)
      OR m.`duplicate_body_sha256` IS NULL OR m.`survivor_body_sha256` IS NULL
      OR SHA2(COALESCE(d.`文章内容`,''),256)<>m.`duplicate_body_sha256`
      OR SHA2(COALESCE(s.`文章内容`,''),256)<>m.`survivor_body_sha256`
    );

  SELECT COUNT(*) AS `待删除文章数`,
         SUM(m.`reason`='article_id') AS `相同文章id`,
         SUM(m.`reason`='article_url') AS `相同链接`,
         SUM(m.`reason`='body_exact') AS `正文完全相同`,
         SUM(m.`reason`='body_similarity') AS `正文双向相似度不少于80%`
  FROM `wechat_post_dedupe_map` m
  JOIN `ods_social_media_post` d ON d.`id`=m.`duplicate_id`
  JOIN `ods_social_media_post` s ON s.`id`=m.`survivor_id`
  WHERE m.`status`='pending' AND m.`duplicate_id`<>m.`survivor_id`
    AND d.`平台`='微信公众号' AND s.`平台`='微信公众号'
    AND d.`文章链接` <=> m.`duplicate_url` AND s.`文章链接` <=> m.`survivor_url`
    AND SHA2(COALESCE(d.`文章内容`,''),256)=m.`duplicate_body_sha256`
    AND SHA2(COALESCE(s.`文章内容`,''),256)=m.`survivor_body_sha256`;

  SELECT m.*, d.`作者名字` AS `重复作者`, d.`文章标题` AS `重复标题`,
         s.`作者名字` AS `保留作者`, s.`文章标题` AS `保留标题`
  FROM `wechat_post_dedupe_map` m
  JOIN `ods_social_media_post` d ON d.`id`=m.`duplicate_id`
  JOIN `ods_social_media_post` s ON s.`id`=m.`survivor_id`
  WHERE m.`status`='pending' AND m.`duplicate_id`<>m.`survivor_id`
    AND d.`平台`='微信公众号' AND s.`平台`='微信公众号'
    AND d.`文章链接` <=> m.`duplicate_url` AND s.`文章链接` <=> m.`survivor_url`
    AND SHA2(COALESCE(d.`文章内容`,''),256)=m.`duplicate_body_sha256`
    AND SHA2(COALESCE(s.`文章内容`,''),256)=m.`survivor_body_sha256`
  ORDER BY m.`survivor_id`,m.`duplicate_id`;

  SELECT invalid_map_count AS `安全校验未通过映射数`,
         IF(invalid_map_count=0,'PASS','BLOCKED：数据库内容已变化或映射不属于微信公众号，请重新生成映射') AS `安全状态`;

  IF do_apply <> 1 THEN
    DO RELEASE_LOCK('wechat_ods_import');
    SELECT 'PREVIEW_ONLY：未修改 ods 表；确认映射后将 @apply_changes 改为 1' AS `执行结果`;
    LEAVE main;
  END IF;

  IF invalid_map_count > 0 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='存在安全校验未通过的待处理映射，拒绝删除；请重新生成映射 SQL';
  END IF;

  /* 固定备份表只追加首次快照，不会覆盖既有备份。 */
  CREATE TABLE IF NOT EXISTS `ods_social_media_post_before_wechat_dedupe` LIKE `ods_social_media_post`;
  INSERT IGNORE INTO `ods_social_media_post_before_wechat_dedupe`
    SELECT p.* FROM `ods_social_media_post` p
    JOIN (
      SELECT `duplicate_id` AS `id` FROM `wechat_post_dedupe_map` WHERE `status`='pending'
      UNION SELECT `survivor_id` FROM `wechat_post_dedupe_map` WHERE `status`='pending'
    ) x ON x.`id`=p.`id`;

  CREATE TABLE IF NOT EXISTS `ods_social_media_comment_before_wechat_dedupe` LIKE `ods_social_media_comment`;
  INSERT IGNORE INTO `ods_social_media_comment_before_wechat_dedupe`
    SELECT * FROM `ods_social_media_comment`
    WHERE `平台`='微信公众号';

  START TRANSACTION;
  SET done=0;
  OPEN post_cursor;
  post_loop: LOOP
    FETCH post_cursor INTO duplicate_id_value, survivor_id_value;
    IF done=1 THEN LEAVE post_loop; END IF;

    UPDATE `ods_social_media_post` s
    JOIN `ods_social_media_post` d ON d.`id`=duplicate_id_value
    SET
      s.`文章图片链接`=CASE WHEN CHAR_LENGTH(COALESCE(d.`文章图片链接`,''))>CHAR_LENGTH(COALESCE(s.`文章图片链接`,'')) THEN d.`文章图片链接` ELSE s.`文章图片链接` END,
      s.`文章图片信息`=NULL,
      s.`作者名字`=COALESCE(NULLIF(s.`作者名字`,''),d.`作者名字`),
      s.`文章标题`=COALESCE(NULLIF(s.`文章标题`,''),d.`文章标题`),
      s.`文章内容`=CASE WHEN CHAR_LENGTH(COALESCE(d.`文章内容`,''))>CHAR_LENGTH(COALESCE(s.`文章内容`,'')) THEN d.`文章内容` ELSE s.`文章内容` END,
      s.`文章标签`=CASE WHEN CHAR_LENGTH(COALESCE(d.`文章标签`,''))>CHAR_LENGTH(COALESCE(s.`文章标签`,'')) THEN d.`文章标签` ELSE s.`文章标签` END,
      s.`文章点赞数`=CASE WHEN s.`文章点赞数` IS NULL AND d.`文章点赞数` IS NULL THEN NULL ELSE GREATEST(COALESCE(s.`文章点赞数`,0),COALESCE(d.`文章点赞数`,0)) END,
      s.`文章收藏数`=CASE WHEN s.`文章收藏数` IS NULL AND d.`文章收藏数` IS NULL THEN NULL ELSE GREATEST(COALESCE(s.`文章收藏数`,0),COALESCE(d.`文章收藏数`,0)) END,
      s.`文章评论数`=CASE WHEN s.`文章评论数` IS NULL AND d.`文章评论数` IS NULL THEN NULL ELSE GREATEST(COALESCE(s.`文章评论数`,0),COALESCE(d.`文章评论数`,0)) END,
      s.`文章分享数`=CASE WHEN s.`文章分享数` IS NULL AND d.`文章分享数` IS NULL THEN NULL ELSE GREATEST(COALESCE(s.`文章分享数`,0),COALESCE(d.`文章分享数`,0)) END,
      s.`作者粉丝数`=CASE WHEN s.`作者粉丝数` IS NULL AND d.`作者粉丝数` IS NULL THEN NULL ELSE GREATEST(COALESCE(s.`作者粉丝数`,0),COALESCE(d.`作者粉丝数`,0)) END,
      s.`作者点赞数`=CASE WHEN s.`作者点赞数` IS NULL AND d.`作者点赞数` IS NULL THEN NULL ELSE GREATEST(COALESCE(s.`作者点赞数`,0),COALESCE(d.`作者点赞数`,0)) END,
      s.`文章id`=COALESCE(NULLIF(s.`文章id`,''),d.`文章id`),
      s.`文章链接`=COALESCE(NULLIF(s.`文章链接`,''),d.`文章链接`),
      s.`作者主页链接`=COALESCE(NULLIF(s.`作者主页链接`,''),d.`作者主页链接`),
      s.`文章视频链接`=CASE WHEN CHAR_LENGTH(COALESCE(d.`文章视频链接`,''))>CHAR_LENGTH(COALESCE(s.`文章视频链接`,'')) THEN d.`文章视频链接` ELSE s.`文章视频链接` END,
      s.`文章视频内容`=CASE WHEN CHAR_LENGTH(COALESCE(d.`文章视频内容`,''))>CHAR_LENGTH(COALESCE(s.`文章视频内容`,'')) THEN d.`文章视频内容` ELSE s.`文章视频内容` END,
      s.`文章视频时长`=CASE WHEN CHAR_LENGTH(COALESCE(d.`文章视频时长`,''))>CHAR_LENGTH(COALESCE(s.`文章视频时长`,'')) THEN d.`文章视频时长` ELSE s.`文章视频时长` END,
      s.`作者id`=COALESCE(NULLIF(s.`作者id`,''),d.`作者id`),
      s.`文章获取时间`=CASE WHEN s.`文章获取时间` IS NULL THEN d.`文章获取时间` WHEN d.`文章获取时间` IS NULL THEN s.`文章获取时间` ELSE LEAST(s.`文章获取时间`,d.`文章获取时间`) END,
      s.`文章标注`=CASE WHEN CHAR_LENGTH(COALESCE(d.`文章标注`,''))>CHAR_LENGTH(COALESCE(s.`文章标注`,'')) THEN d.`文章标注` ELSE s.`文章标注` END,
      s.`分类`=COALESCE(NULLIF(s.`分类`,''),d.`分类`),
      s.`清洗标注`=CASE WHEN CHAR_LENGTH(COALESCE(d.`清洗标注`,''))>CHAR_LENGTH(COALESCE(s.`清洗标注`,'')) THEN d.`清洗标注` ELSE s.`清洗标注` END,
      s.`项目`=COALESCE(NULLIF(s.`项目`,''),d.`项目`),
      s.`关键词`=COALESCE(NULLIF(s.`关键词`,''),d.`关键词`),
      s.`地点`=COALESCE(NULLIF(s.`地点`,''),d.`地点`),
      s.`内容类型`=COALESCE(NULLIF(s.`内容类型`,''),d.`内容类型`),
      s.`是否广告`=COALESCE(NULLIF(s.`是否广告`,''),d.`是否广告`),
      s.`广告关键词`=COALESCE(NULLIF(s.`广告关键词`,''),d.`广告关键词`)
    WHERE s.`id`=survivor_id_value;

    UPDATE `ods_social_media_comment` c
    JOIN `ods_social_media_post` d ON d.`id`=duplicate_id_value
    JOIN `ods_social_media_post` s ON s.`id`=survivor_id_value
    SET c.`文章id`=s.`文章id`, c.`文章链接`=s.`文章链接`,
        c.`关键词`=COALESCE(NULLIF(c.`关键词`,''),s.`关键词`),
        c.`项目`=COALESCE(NULLIF(c.`项目`,''),s.`项目`)
    WHERE c.`平台`='微信公众号'
      AND ((NULLIF(d.`文章id`,'') IS NOT NULL AND c.`文章id`=d.`文章id`)
        OR (NULLIF(d.`文章链接`,'') IS NOT NULL AND c.`文章链接`=d.`文章链接`));

    DELETE FROM `ods_social_media_post` WHERE `id`=duplicate_id_value;
  END LOOP;
  CLOSE post_cursor;
  UPDATE `wechat_post_dedupe_map` m
  JOIN `ods_social_media_post_before_wechat_dedupe` b ON b.`id`=m.`duplicate_id`
  LEFT JOIN `ods_social_media_post` p ON p.`id`=m.`duplicate_id`
  SET m.`status`='applied',m.`applied_at`=NOW()
  WHERE m.`status`='pending' AND p.`id` IS NULL;

  /* 评论在文章重绑后按评论id；无评论id时按文章+正文+时间去重。 */
  DELETE FROM `wechat_comment_dedupe_map` WHERE `status`='pending';
  DROP TEMPORARY TABLE IF EXISTS `tmp_wechat_comment_rank`;
  CREATE TEMPORARY TABLE `tmp_wechat_comment_rank` AS
  SELECT q.*,
         ROW_NUMBER() OVER (PARTITION BY q.`natural_key` ORDER BY q.`comment_at`,q.`fetched_at`,q.`id`) AS `rn`
  FROM (
    SELECT c.`id`,
      CASE WHEN NULLIF(TRIM(c.`评论id`),'') IS NOT NULL
        THEN CONCAT(TRIM(c.`平台`),'|comment-id|',TRIM(c.`评论id`))
        ELSE CONCAT(TRIM(c.`平台`),'|fallback|',COALESCE(NULLIF(c.`文章id`,''),c.`文章链接`,''),'|',REGEXP_REPLACE(LOWER(COALESCE(c.`评论内容`,'')),'[[:space:]]+',''),'|',COALESCE(c.`评论时间`,'')) END AS `natural_key`,
      COALESCE(STR_TO_DATE(REPLACE(LEFT(c.`评论时间`,19),'T',' '),'%Y-%m-%d %H:%i:%s'),CAST('9999-12-31 23:59:59' AS DATETIME)) AS `comment_at`,
      COALESCE(c.`评论获取时间`,CAST('9999-12-31 23:59:59' AS DATETIME)) AS `fetched_at`
    FROM `ods_social_media_comment` c
    WHERE c.`平台`='微信公众号'
  ) q;

  INSERT IGNORE INTO `wechat_comment_dedupe_map` (`duplicate_id`,`survivor_id`,`reason`)
  SELECT d.`id`,s.`id`,IF(d.`natural_key` LIKE '%|comment-id|%','comment_id','comment_fallback')
  FROM `tmp_wechat_comment_rank` d
  JOIN `tmp_wechat_comment_rank` s ON s.`natural_key`=d.`natural_key` AND s.`rn`=1
  WHERE d.`rn`>1 AND d.`id`<>s.`id`;

  SET done=0;
  OPEN comment_cursor;
  comment_loop: LOOP
    FETCH comment_cursor INTO duplicate_id_value, survivor_id_value;
    IF done=1 THEN LEAVE comment_loop; END IF;
    UPDATE `ods_social_media_comment` s
    JOIN `ods_social_media_comment` d ON d.`id`=duplicate_id_value
    SET s.`评论用户链接`=COALESCE(NULLIF(s.`评论用户链接`,''),d.`评论用户链接`),
        s.`评论用户id`=COALESCE(NULLIF(s.`评论用户id`,''),d.`评论用户id`),
        s.`评论用户名字`=COALESCE(NULLIF(s.`评论用户名字`,''),d.`评论用户名字`),
        s.`评论IP`=COALESCE(NULLIF(s.`评论IP`,''),d.`评论IP`),
        s.`评论点赞数`=CASE WHEN s.`评论点赞数` IS NULL AND d.`评论点赞数` IS NULL THEN NULL ELSE GREATEST(COALESCE(s.`评论点赞数`,0),COALESCE(d.`评论点赞数`,0)) END,
        s.`评论回复数`=CASE WHEN s.`评论回复数` IS NULL AND d.`评论回复数` IS NULL THEN NULL ELSE GREATEST(COALESCE(s.`评论回复数`,0),COALESCE(d.`评论回复数`,0)) END,
        s.`清洗标注`=COALESCE(NULLIF(s.`清洗标注`,''),d.`清洗标注`)
    WHERE s.`id`=survivor_id_value;
    DELETE FROM `ods_social_media_comment` WHERE `id`=duplicate_id_value;
  END LOOP;
  CLOSE comment_cursor;
  UPDATE `wechat_comment_dedupe_map` m
  JOIN `ods_social_media_comment_before_wechat_dedupe` b ON b.`id`=m.`duplicate_id`
  LEFT JOIN `ods_social_media_comment` c ON c.`id`=m.`duplicate_id`
  SET m.`status`='applied',m.`applied_at`=NOW()
  WHERE m.`status`='pending' AND c.`id` IS NULL;

  COMMIT;
  DO RELEASE_LOCK('wechat_ods_import');
  SELECT SUM(`status`='applied') AS `已应用文章映射`,SUM(`status`='pending') AS `仍待处理文章映射`
  FROM `wechat_post_dedupe_map`;
  SELECT SUM(`status`='applied') AS `已应用评论映射`,SUM(`status`='pending') AS `仍待处理评论映射`
  FROM `wechat_comment_dedupe_map`;
  SELECT COUNT(*) AS `公众号剩余文章数` FROM `ods_social_media_post`
  WHERE `平台`='微信公众号';
  SELECT 'APPLIED：已备份、合并、重绑评论并删除重复行' AS `执行结果`;
END$$
DELIMITER ;

CALL `run_wechat_post_dedupe`(@apply_changes);
DROP PROCEDURE IF EXISTS `run_wechat_post_dedupe`;
