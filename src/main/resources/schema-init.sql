-- ============================================================================
-- 首启自动建库脚本（打进 jar，由 DatabaseBootstrapConfig 在 DataSource 初始化前跑）
--
-- 与 docs/schema.sql 的分工：
--   · 本文件 = 幂等自动建（CREATE TABLE IF NOT EXISTS + INSERT IGNORE，绝不 DROP）。
--     后端每次启动都跑一遍：库/表/角色/权限缺什么补什么，已有的原样保留——
--     升级版本、重装客户端都不会清掉用户的搜题记录。
--   · docs/schema.sql = 手动重建参考（DROP TABLE 先删后建），只在需要清空重来时用。
--
-- 为什么必须播种角色/权限：register() 查不到 ADMIN/USER 角色会直接抛
-- 「角色数据缺失，请先执行六表 SQL」，所以只建表不播种的话用户仍要手动碰 SQL。
-- 用户表故意不播种（口令红线：绝不预置任何账号），首个注册者由 register() 赋 ADMIN。
--
-- sys_config 是运行时键值表（device_token/lan_token/storage_dir），TokenService
-- 与 StorageService 会自己 insert，无需播种。
--
-- 顺序硬要求：先建全部表、再播种。Spring ScriptUtils 首错即停（continueOnError=false），
-- 全新库上表还不存在就 INSERT 会直接失败。建表按外键依赖排序：role → user → category → article。
-- ============================================================================

-- ---- 业务表 ----
CREATE TABLE IF NOT EXISTS `role` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `code` varchar(32) COLLATE utf8mb4_general_ci NOT NULL COMMENT '角色标识 ADMIN/USER',
  `name` varchar(64) COLLATE utf8mb4_general_ci NOT NULL COMMENT '角色名',
  `remark` varchar(255) COLLATE utf8mb4_general_ci DEFAULT NULL,
  `created_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `deleted` tinyint NOT NULL DEFAULT '0' COMMENT '逻辑删除 0否1是',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_role_code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='角色表';

CREATE TABLE IF NOT EXISTS `user` (
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='用户表';

CREATE TABLE IF NOT EXISTS `category` (
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

CREATE TABLE IF NOT EXISTS `article` (
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

CREATE TABLE IF NOT EXISTS `permission` (
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='权限表（细粒度，AOP 读这张表）';

CREATE TABLE IF NOT EXISTS `op_log` (
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='操作日志表（只增不改，不设 deleted/update_time）';

CREATE TABLE IF NOT EXISTS `sys_config` (
  `key` varchar(64) COLLATE utf8mb4_general_ci NOT NULL,
  `value` text COLLATE utf8mb4_general_ci,
  `update_time` datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='键值配置表（辅助，非业务六表）';

-- ---- 种子：角色（唯一键 uk_role_code → INSERT IGNORE 幂等） ----
INSERT IGNORE INTO `role` (`code`, `name`, `remark`) VALUES
  ('ADMIN', '管理员', '首个注册用户自动获得'),
  ('USER',  '普通用户', '后续注册用户默认获得');

-- ---- 种子：权限（唯一键 uk_perm_code_role → INSERT IGNORE 幂等；
--      role_id 按 code 子查询取，不硬编码 id——不同库自增起点可能不同） ----
-- ADMIN 7 条（与 @RequirePermission 用到的 7 个权限码一一对应）
INSERT IGNORE INTO `permission` (`code`, `name`, `role_id`)
SELECT 'article:create',  '新建搜题记录',  `id` FROM `role` WHERE `code` = 'ADMIN';
INSERT IGNORE INTO `permission` (`code`, `name`, `role_id`)
SELECT 'article:edit',    '编辑搜题记录',  `id` FROM `role` WHERE `code` = 'ADMIN';
INSERT IGNORE INTO `permission` (`code`, `name`, `role_id`)
SELECT 'article:delete',  '删除搜题记录',  `id` FROM `role` WHERE `code` = 'ADMIN';
INSERT IGNORE INTO `permission` (`code`, `name`, `role_id`)
SELECT 'article:audit',   '审核搜题记录',  `id` FROM `role` WHERE `code` = 'ADMIN';
INSERT IGNORE INTO `permission` (`code`, `name`, `role_id`)
SELECT 'category:manage', '分类管理',      `id` FROM `role` WHERE `code` = 'ADMIN';
INSERT IGNORE INTO `permission` (`code`, `name`, `role_id`)
SELECT 'user:manage',     '用户与角色管理', `id` FROM `role` WHERE `code` = 'ADMIN';
INSERT IGNORE INTO `permission` (`code`, `name`, `role_id`)
SELECT 'log:view',        '查看日志',      `id` FROM `role` WHERE `code` = 'ADMIN';
-- USER 4 条（普通用户只够自管记录与科目）
INSERT IGNORE INTO `permission` (`code`, `name`, `role_id`)
SELECT 'article:create',  '新建搜题记录',    `id` FROM `role` WHERE `code` = 'USER';
INSERT IGNORE INTO `permission` (`code`, `name`, `role_id`)
SELECT 'article:edit',    '编辑自己的记录',  `id` FROM `role` WHERE `code` = 'USER';
INSERT IGNORE INTO `permission` (`code`, `name`, `role_id`)
SELECT 'article:delete',  '删除自己的记录',  `id` FROM `role` WHERE `code` = 'USER';
INSERT IGNORE INTO `permission` (`code`, `name`, `role_id`)
SELECT 'category:manage', '使用科目分类',    `id` FROM `role` WHERE `code` = 'USER';
