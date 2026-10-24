/* 本次整理：2026-10-08。
   计算表：ods_social_media_post；沿用此前指标定义与权重。
   范围：仅两专题的全部文章记录，不抽样、不限制平台。
   前提：已经存在热度指数、互动深度指数两个字段；没有则先运行01新增字段脚本。
   预览：保持下文@apply_changes=0；补算：确认预览后改为1重新整段运行。
   评分基准：两个专题合并后按平台+内容类型分组，不按专题分别排名。
   NULL表示该记录不满足计算条件；不是零互动。
   仅补算数据库NULL字段，已有分数（包括0）原样保留；两个字段分别判断。
   所有文章参与同平台同类型基准，只有缺失字段回填；不把缺失行单独排名。
   混合历史版本或历史基准的旧分数不重新校准；新增数据后旧分数与新分数可能不完全可比。
   无法计算的缺失字段保持NULL，不虚构0。
   这是SQL编写交付，未连接数据库执行，也未改变任何数据库记录。
*/

/* MySQL 8.0；先运行01新增字段。
   仅处理项目字段精确等于“北京臻澐项目口碑”或“全国地产设计产品力监测”的行。
   其他项目、空项目、多个项目拼接字符串不参与计算，也不回填。
   默认预览：@apply_changes=0；改为1才更新两个指标。
   @platform_scope=NULL：处理这两个项目内的所有平台，不是全表。
   如指定@platform_scope='小红书'，则仅处理这两个项目内的小红书。
   基准为两个项目范围内的全量数据，仍按平台＋内容类型分组；
   两项目同平台同类型共享基准，不按项目再次拆分，不合并门户平台。
   更新只SET两个新增字段；没有DELETE，不改原采集字段。
   只创建一个会话临时结果表；结束时删除，连接断开也自动消失。
   请在同一连接整段运行；遇到错误停止并ROLLBACK，勿继续COMMIT。
   正式执行前暂停采集/修改互动数；建议使用InnoDB表。
   此脚本未连接生产库验证，请先在测试库核验。

   口径：平均秩/n，不使用PERCENT_RANK或CUME_DIST替代。
   热度权重：点赞.27，推荐/收藏.27，分享.26，评论.20；缺失重归一。
   微信公众号、微信视频号、视频号的收藏字段含义为推荐；其余为收藏。
   当前两者权重相同，仅语义不同，不虚构额外推荐字段或重复计数。
   互动：V=点赞+推荐/收藏+2分享+3评论；D=2分享+3评论；
   μ=ΣD/ΣV，κ=max(正V中位数,1)，R=(D+κμ)/(V+κ)。
   互动深度指数=100*(.4*Q(LN(1+V))+.6*Q(R))。
   不含未提供的阅读/播放量、评论获赞、楼中楼互动。
   全零/无变化字段不可用；每行至少2项可用。原字段空白≠0。
   数值解析接受普通十进制；带“万/千/+”等展示文字暂视为缺失。
   P99.5线性插值截尾只用于热度Q；V、D仍使用未截尾有效原计数。
   分数依赖同组全量样本；新数据加入或互动数变化需重算同组。
*/
SET NAMES utf8mb4;
SET @apply_changes := 0;
SET @platform_scope := NULL;

DROP TEMPORARY TABLE IF EXISTS tmp_post_interaction_score_v1;
SET TRANSACTION ISOLATION LEVEL REPEATABLE READ;
START TRANSACTION WITH CONSISTENT SNAPSHOT;

CREATE TEMPORARY TABLE tmp_post_interaction_score_v1 AS
WITH
source_rows AS (
  SELECT p.`id`,
    CAST(SHA2(CAST(JSON_ARRAY(
      COALESCE(NULLIF(p.`平台`,''),'未标明平台'),
      COALESCE(NULLIF(p.`内容类型`,''),'未标明类型')
    ) AS CHAR),256) AS BINARY(64)) AS g,
    p.`项目` AS project_name,
    p.`平台` AS platform_name, p.`内容类型` AS content_type,
    p.`文章点赞数` AS raw_l, p.`文章收藏数` AS raw_x,
    p.`文章分享数` AS raw_s, p.`文章评论数` AS raw_c
  FROM `ods_social_media_post` p
  WHERE CAST(p.`项目` AS BINARY) IN (
      CAST('北京臻澐项目口碑' AS BINARY),
      CAST('全国地产设计产品力监测' AS BINARY)
    )
    AND (@platform_scope IS NULL
      OR CAST(p.`平台` AS BINARY)=CAST(@platform_scope AS BINARY))
),
metric_text AS (
  SELECT a.`id`,a.g,b.metric,b.heat_weight,b.depth_weight,
    TRIM(CAST(CASE b.metric
      WHEN 1 THEN a.raw_l WHEN 2 THEN a.raw_x
      WHEN 3 THEN a.raw_s WHEN 4 THEN a.raw_c END AS CHAR)) AS txt
  FROM source_rows a
  CROSS JOIN (
    SELECT 1 AS metric,0.27 AS heat_weight,1 AS depth_weight
    UNION ALL SELECT 2,0.27,1
    UNION ALL SELECT 3,0.26,2
    UNION ALL SELECT 4,0.20,3
  ) b
),
parsed AS (
  SELECT `id`,g,metric,heat_weight,depth_weight,
    CASE WHEN REGEXP_LIKE(txt,'^[-+]?[0-9]+([.][0-9]+)?$')
      THEN GREATEST(CAST(txt AS DECIMAL(30,6)),0) ELSE NULL END AS v
  FROM metric_text
),
metric_stats AS (
  SELECT g,metric,COUNT(v) AS n,COUNT(DISTINCT v) AS unique_n,MAX(v) AS max_v
  FROM parsed GROUP BY g,metric
),
valid_metrics AS (
  SELECT p.*,s.n,
    ROW_NUMBER() OVER(PARTITION BY p.g,p.metric ORDER BY p.v,p.`id`) AS rn
  FROM parsed p JOIN metric_stats s ON p.g=s.g AND p.metric=s.metric
  WHERE s.n>=5 AND s.unique_n>1 AND s.max_v>0 AND p.v IS NOT NULL
),
cap_bounds AS (
  SELECT g,metric,MAX(n) AS n,
    MAX(CASE WHEN rn=FLOOR(1+(n-1)*0.995) THEN v END) AS lo,
    MAX(CASE WHEN rn=CEIL(1+(n-1)*0.995) THEN v END) AS hi
  FROM valid_metrics GROUP BY g,metric
),
caps AS (
  SELECT g,metric,
    lo+(hi-lo)*(1+(n-1)*0.995-FLOOR(1+(n-1)*0.995)) AS cap
  FROM cap_bounds
),
transformed AS (
  SELECT m.*,LN(1+LEAST(m.v,c.cap)) AS z
  FROM valid_metrics m JOIN caps c ON m.g=c.g AND m.metric=c.metric
),
metric_percentiles AS (
  SELECT *,
    (RANK() OVER(PARTITION BY g,metric ORDER BY z)
      +(COUNT(*) OVER(PARTITION BY g,metric,z)-1)/2.0)/n AS q
  FROM transformed
),
row_metrics AS (
  SELECT `id`,g,COUNT(*) AS available_n,
    SUM(heat_weight*q)/SUM(heat_weight)*100 AS heat,
    SUM(depth_weight*v) AS volume_v,
    SUM(CASE WHEN metric IN (3,4) THEN depth_weight*v ELSE 0 END) AS depth_d
  FROM metric_percentiles GROUP BY `id`,g
),
eligible AS (
  SELECT * FROM row_metrics WHERE available_n>=2
),
positive_volumes AS (
  SELECT g,volume_v,
    ROW_NUMBER() OVER(PARTITION BY g ORDER BY volume_v,`id`) AS rn,
    COUNT(*) OVER(PARTITION BY g) AS n
  FROM eligible WHERE volume_v>0
),
group_kappa AS (
  SELECT g,GREATEST(AVG(volume_v),1) AS kappa
  FROM positive_volumes
  WHERE rn IN (FLOOR((n+1)/2),FLOOR((n+2)/2)) GROUP BY g
),
group_prior AS (
  SELECT g,SUM(depth_d)/NULLIF(SUM(volume_v),0) AS mu
  FROM eligible GROUP BY g
),
smoothed AS (
  SELECT e.*,
    (e.depth_d+k.kappa*p.mu)/(e.volume_v+k.kappa) AS depth_r,
    LN(1+e.volume_v) AS log_v
  FROM eligible e JOIN group_kappa k ON e.g=k.g
    JOIN group_prior p ON e.g=p.g
),
depth_percentiles AS (
  SELECT *,
    (RANK() OVER(PARTITION BY g ORDER BY log_v)
      +(COUNT(*) OVER(PARTITION BY g,log_v)-1)/2.0)
      /COUNT(*) OVER(PARTITION BY g) AS qv,
    (RANK() OVER(PARTITION BY g ORDER BY depth_r)
      +(COUNT(*) OVER(PARTITION BY g,depth_r)-1)/2.0)
      /COUNT(*) OVER(PARTITION BY g) AS qr
  FROM smoothed
)
SELECT a.`id`,a.project_name,a.platform_name,a.content_type,
  a.raw_l,a.raw_x,a.raw_s,a.raw_c,
  CAST(ROUND(e.heat,2) AS DECIMAL(5,2)) AS heat_score,
  CAST(ROUND(100*(0.4*d.qv+0.6*d.qr),2) AS DECIMAL(5,2)) AS depth_score
FROM source_rows a
LEFT JOIN eligible e ON a.`id`=e.`id`
LEFT JOIN depth_percentiles d ON a.`id`=d.`id`;

/* 分组基准统计：只含两个项目，不把抽样50条当成总体。 */
SELECT platform_name AS `平台`,content_type AS `内容类型`,COUNT(*) AS `基准行数`,
  COUNT(heat_score) AS `热度可计算行数`,COUNT(depth_score) AS `互动可计算行数`
FROM tmp_post_interaction_score_v1 GROUP BY platform_name,content_type;

/* 各项目覆盖统计；项目拆开显示，但评分基准仍为平台＋内容类型。 */
SELECT project_name AS `项目`,platform_name AS `平台`,content_type AS `内容类型`,
  COUNT(*) AS `范围内行数`,COUNT(heat_score) AS `热度可计算行数`,
  COUNT(depth_score) AS `互动可计算行数`
FROM tmp_post_interaction_score_v1
GROUP BY project_name,platform_name,content_type;

/* 仅预览缺失字段；已有分数不覆盖。0是有效分数，不视为缺失。 */
SELECT COUNT(*) AS `范围内文章数`,
  SUM(p.`热度指数` IS NULL) AS `热度缺失文章数`,
  SUM(p.`互动深度指数` IS NULL) AS `互动缺失文章数`,
  SUM(p.`热度指数` IS NULL AND r.heat_score IS NOT NULL) AS `热度可补算数`,
  SUM(p.`互动深度指数` IS NULL AND r.depth_score IS NOT NULL) AS `互动可补算数`
FROM tmp_post_interaction_score_v1 r JOIN `ods_social_media_post` p ON p.`id`=r.`id`;

SELECT r.`id`,r.project_name AS `项目`,r.platform_name AS `平台`,r.content_type AS `内容类型`,
  p.`热度指数` AS `现有热度指数`,p.`互动深度指数` AS `现有互动深度指数`,
  CASE WHEN p.`热度指数` IS NULL THEN r.heat_score ELSE NULL END AS `拟补热度指数`,
  CASE WHEN p.`互动深度指数` IS NULL THEN r.depth_score ELSE NULL END AS `拟补互动深度指数`
FROM tmp_post_interaction_score_v1 r JOIN `ods_social_media_post` p ON p.`id`=r.`id`
WHERE p.`热度指数` IS NULL OR p.`互动深度指数` IS NULL
ORDER BY r.`id` LIMIT 50;

/* 乐观核验：当前项目、四项计数及平台类型与计算快照一致才回填。
   比较统一使用二进制，避免混用utf8mb4排序规则。
   仅补算NULL字段，已有分数不覆盖；无法计算的缺失字段保持NULL。
*/
UPDATE `ods_social_media_post` p
JOIN tmp_post_interaction_score_v1 r ON p.`id`=r.`id`
SET p.`热度指数`=CASE WHEN p.`热度指数` IS NULL THEN r.heat_score ELSE p.`热度指数` END,
    p.`互动深度指数`=CASE WHEN p.`互动深度指数` IS NULL THEN r.depth_score ELSE p.`互动深度指数` END
WHERE @apply_changes=1
  AND ((p.`热度指数` IS NULL AND r.heat_score IS NOT NULL)
    OR (p.`互动深度指数` IS NULL AND r.depth_score IS NOT NULL))
  AND CAST(p.`项目` AS BINARY) IN (
    CAST('北京臻澐项目口碑' AS BINARY),
    CAST('全国地产设计产品力监测' AS BINARY)
  )
  AND (CAST(p.`项目` AS BINARY) <=> CAST(r.project_name AS BINARY))
  AND (CAST(p.`平台` AS BINARY) <=> CAST(r.platform_name AS BINARY))
  AND (CAST(p.`内容类型` AS BINARY) <=> CAST(r.content_type AS BINARY))
  AND (CAST(p.`文章点赞数` AS BINARY) <=> CAST(r.raw_l AS BINARY))
  AND (CAST(p.`文章收藏数` AS BINARY) <=> CAST(r.raw_x AS BINARY))
  AND (CAST(p.`文章分享数` AS BINARY) <=> CAST(r.raw_s AS BINARY))
  AND (CAST(p.`文章评论数` AS BINARY) <=> CAST(r.raw_c AS BINARY));
SELECT @apply_changes AS `执行开关`,ROW_COUNT() AS `本次更新返回行数`;
COMMIT;
DROP TEMPORARY TABLE IF EXISTS tmp_post_interaction_score_v1;
