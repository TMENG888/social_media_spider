-- 一次性升级已有云数据库表。执行前建议先做结构备份。
-- 只转换字符集/排序规则，不删除、合并或重排任何业务记录。
ALTER TABLE `ods_social_media_post`
  CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

ALTER TABLE `ods_social_media_comment`
  CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
