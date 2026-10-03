
/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

CREATE DATABASE /*!32312 IF NOT EXISTS*/ `spore_cms` /*!40100 DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci */ /*!80016 DEFAULT ENCRYPTION='N' */;

USE `spore_cms`;
DROP TABLE IF EXISTS `article`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `article` (
  `id` varchar(32) COLLATE utf8mb4_general_ci NOT NULL COMMENT '会话 id：yyyyMMdd-HHmmssSSS，与手机端文件名同源',
  `user_id` bigint NOT NULL COMMENT '外键→user',
  `category_id` varchar(32) COLLATE utf8mb4_general_ci DEFAULT NULL COMMENT '外键→category；NULL=未分组（删科目回未分组）',
  `title` varchar(200) COLLATE utf8mb4_general_ci NOT NULL DEFAULT '新会话',
  `content` json NOT NULL COMMENT 'messages 数组整体落 JSON（见 03 映射表）',
  `fav` tinyint NOT NULL DEFAULT '0' COMMENT '收藏（只标记不置顶）',
  `status` varchar(20) COLLATE utf8mb4_general_ci NOT NULL DEFAULT 'done' COMMENT '会话态 done/error/aborted/…',
  `audit_status` tinyint NOT NULL DEFAULT '1' COMMENT '审核流 0草稿 1待审 2通过 3驳回',
  `origin` varchar(8) COLLATE utf8mb4_general_ci NOT NULL DEFAULT 'gui' COMMENT '来源 mobile/gui（防重复导入）',
  `attachment_path` varchar(255) COLLATE utf8mb4_general_ci DEFAULT NULL COMMENT '题图相对题库目录的路径（DB只存相对路径）',
  `created_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime(3) DEFAULT NULL,
  `deleted` tinyint NOT NULL DEFAULT '0' COMMENT '墓碑：1 也随 since 下发',
  PRIMARY KEY (`id`),
  KEY `idx_art_user` (`user_id`),
  KEY `idx_art_cat` (`category_id`),
  KEY `idx_art_sync` (`update_time`) COMMENT 'since 增量游标索引',
  KEY `idx_art_title` (`title`(40)) COMMENT '模糊检索前缀索引',
  CONSTRAINT `fk_art_cat` FOREIGN KEY (`category_id`) REFERENCES `category` (`id`),
  CONSTRAINT `fk_art_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='文章表（搜题记录）';
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `category`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `category` (
  `id` varchar(32) COLLATE utf8mb4_general_ci NOT NULL COMMENT '字符串 id：时间戳/UUID，两端同步同名空间，禁自增',
  `user_id` bigint NOT NULL COMMENT '外键→user（谁建的）',
  `parent_id` varchar(32) COLLATE utf8mb4_general_ci DEFAULT NULL COMMENT 'NULL=顶层；外键→category 自关联多级',
  `name` varchar(64) COLLATE utf8mb4_general_ci NOT NULL COMMENT '科目名（如 数学）',
  `sort_order` int NOT NULL DEFAULT '0' COMMENT '排序',
  `status` tinyint NOT NULL DEFAULT '1' COMMENT '1启 0停（状态启停考点）',
  `created_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime(3) DEFAULT NULL,
  `deleted` tinyint NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`),
  KEY `idx_cat_parent` (`parent_id`),
  KEY `idx_cat_user` (`user_id`),
  KEY `idx_cat_update` (`update_time`),
  CONSTRAINT `fk_cat_parent` FOREIGN KEY (`parent_id`) REFERENCES `category` (`id`),
  CONSTRAINT `fk_cat_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='分类表（科目，多级）';
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `op_log`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `op_log` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `user_id` bigint DEFAULT NULL COMMENT '外键→user；系统动作可空',
  `action` varchar(64) COLLATE utf8mb4_general_ci NOT NULL COMMENT '如 article.delete / user.login',
  `target` varchar(128) COLLATE utf8mb4_general_ci DEFAULT NULL COMMENT '对象 id/名',
  `detail` varchar(512) COLLATE utf8mb4_general_ci DEFAULT NULL,
  `ip` varchar(45) COLLATE utf8mb4_general_ci DEFAULT NULL,
  `created_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_log_user` (`user_id`),
  KEY `idx_log_time` (`created_time`),
  CONSTRAINT `fk_log_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=109 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='操作日志表（只增不改，不设 deleted/update_time）';
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `permission`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `permission` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `code` varchar(64) COLLATE utf8mb4_general_ci NOT NULL COMMENT '如 article:delete / category:edit',
  `name` varchar(64) COLLATE utf8mb4_general_ci NOT NULL,
  `role_id` bigint NOT NULL COMMENT '外键→role（角色-权限直接关联，够课程用）',
  `created_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `deleted` tinyint NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_perm_code_role` (`code`,`role_id`),
  KEY `idx_perm_role` (`role_id`),
  CONSTRAINT `fk_perm_role` FOREIGN KEY (`role_id`) REFERENCES `role` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=12 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='权限表（细粒度，AOP 读这张表）';
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `role`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `role` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `code` varchar(32) COLLATE utf8mb4_general_ci NOT NULL COMMENT '角色标识 ADMIN/USER',
  `name` varchar(64) COLLATE utf8mb4_general_ci NOT NULL COMMENT '角色名',
  `remark` varchar(255) COLLATE utf8mb4_general_ci DEFAULT NULL,
  `created_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `deleted` tinyint NOT NULL DEFAULT '0' COMMENT '逻辑删除 0否1是',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_role_code` (`code`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='角色表';
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `sys_config`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `sys_config` (
  `key` varchar(64) COLLATE utf8mb4_general_ci NOT NULL,
  `value` text COLLATE utf8mb4_general_ci,
  `update_time` datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='键值配置表（辅助，非业务六表）';
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `user`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `user` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `username` varchar(64) COLLATE utf8mb4_general_ci NOT NULL COMMENT '登录名',
  `password` varchar(100) COLLATE utf8mb4_general_ci NOT NULL COMMENT 'BCrypt 哈希，绝不明文',
  `nickname` varchar(64) COLLATE utf8mb4_general_ci DEFAULT NULL,
  `role_id` bigint NOT NULL COMMENT '外键→role',
  `status` tinyint NOT NULL DEFAULT '1' COMMENT '1启用 0停用',
  `created_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `deleted` tinyint NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_user_username` (`username`),
  KEY `idx_user_role` (`role_id`),
  CONSTRAINT `fk_user_role` FOREIGN KEY (`role_id`) REFERENCES `role` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='用户表';
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

