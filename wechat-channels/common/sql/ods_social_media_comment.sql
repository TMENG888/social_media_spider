/*
 Navicat Premium Dump SQL

 Source Server         : 全国地产设计产品力监测
 Source Server Type    : MySQL
 Source Server Version : 80036 (8.0.36)
 Source Host           : 127.0.0.1:3306
 Source Schema         : social

 Target Server Type    : MySQL
 Target Server Version : 80036 (8.0.36)
 File Encoding         : 65001

 Date: 15/09/2026 12:03:35
*/

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ----------------------------
-- Table structure for ods_social_media_comment
-- ----------------------------
DROP TABLE IF EXISTS `ods_social_media_comment`;
CREATE TABLE `ods_social_media_comment`  (
  `id` bigint NOT NULL,
  `评论id` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL,
  `评论用户链接` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL,
  `评论用户id` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL,
  `评论用户名字` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL,
  `评论内容` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL,
  `评论时间` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL,
  `评论IP` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL,
  `评论点赞数` bigint NULL DEFAULT NULL,
  `评论回复数` bigint NULL DEFAULT NULL,
  `文章链接` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL,
  `文章id` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL,
  `关键词` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL,
  `评论获取时间` datetime NULL DEFAULT NULL,
  `平台` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL,
  `分类` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL,
  `项目` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL,
  `清洗标注` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL,
  PRIMARY KEY (`id`) USING BTREE,
  INDEX `idx_分类_id`(`分类`(128) ASC, `id` ASC) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci ROW_FORMAT = Dynamic;

SET FOREIGN_KEY_CHECKS = 1;
