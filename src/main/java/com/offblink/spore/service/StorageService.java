package com.offblink.spore.service;

import java.util.Map;

/**
 * 题库目录（附件存储）：当前路径查询 + 切换迁移（handoff §2 协议）。
 * DB 只存相对路径——切目录 = 搬文件 + 改配置，MySQL 行零改动。
 */
public interface StorageService {

    /** 当前生效的题库目录绝对路径 */
    String currentDir();

    /** 现状：{path, fileCount, bytes} */
    Map<String, Object> info();

    /**
     * 切换到新目录。协议（禁止裸 move）：
     * copy → 校验（文件数+字节数）→ 切配置(sys_config) → 删旧目录。
     * 任一步失败：留在旧目录、配置不动、清理半成品，抛业务异常。
     */
    Map<String, Object> switchTo(String targetPath);
}
