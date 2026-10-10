/*
 Navicat Premium Dump SQL

 Source Server         : 全国地产设计产品力监测
 Source Server Type    : MySQL
 Source Server Version : 80036 (8.0.36)
 Source Host           : mysql.example.com:3306
 Source Schema         : social

 Target Server Type    : MySQL
 Target Server Version : 80036 (8.0.36)
 File Encoding         : 65001

 Date: 09/09/2026 18:47:43
*/

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ----------------------------
-- Table structure for ods_social_media_post
-- ----------------------------
DROP TABLE IF EXISTS `ods_social_media_post`;
CREATE TABLE `ods_social_media_post`  (
  `id` bigint NOT NULL,
  `文章图片链接` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL,
  `文章图片信息` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL,
  `作者名字` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL,
  `文章标题` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL,
  `文章内容` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL,
  `文章标签` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL,
  `文章时间地点` varchar(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL,
  `文章点赞数` int NULL DEFAULT NULL,
  `文章收藏数` int NULL DEFAULT NULL,
  `文章评论数` int NULL DEFAULT NULL,
  `文章链接` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL,
  `文章id` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL,
  `作者主页链接` varchar(1000) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL,
  `文章视频链接` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL,
  `文章视频内容` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL,
  `关键词` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL,
  `作者id` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL,
  `作者粉丝数` bigint NULL DEFAULT NULL,
  `作者点赞数` bigint NULL DEFAULT NULL,
  `文章分享数` bigint NULL DEFAULT NULL,
  `文章视频时长` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL,
  `平台` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL,
  `文章获取时间` datetime NULL DEFAULT NULL,
  `文章标注` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL,
  `分类` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL,
  `清洗标注` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL,
  `项目` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL,
  `地点` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL,
  `内容类型` varchar(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL,
  `是否广告` varchar(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL,
  `广告关键词` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL,
  PRIMARY KEY (`id`) USING BTREE,
  INDEX `idx_分类_id`(`分类`(128) ASC, `id` ASC) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci ROW_FORMAT = Dynamic;

SET FOREIGN_KEY_CHECKS = 1;
