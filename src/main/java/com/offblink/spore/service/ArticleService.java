package com.offblink.spore.service;

import com.offblink.spore.controller.dto.ArticleReq;
import com.offblink.spore.controller.dto.ArticleVO;
import com.offblink.spore.controller.dto.PageResult;

import java.util.List;

/**
 * 文章（搜题记录）服务（design/02 第三节）：
 * 分页多条件检索 + CRUD + 批量审核/发布/删除。正文 = messages 数组整体 JSON，禁止有损。
 */
public interface ArticleService {

    /** 分页检索：keyword 走 title；categoryId/status/fav 精确；sort 默认 update_time desc */
    PageResult<ArticleVO> page(Long userId, int page, int size, String keyword,
                               String categoryId, String status, Integer fav, String sort);

    ArticleVO get(Long userId, String id);

    /** 新建（GUI 侧建的记录 origin=gui） */
    ArticleVO create(Long userId, ArticleReq req);

    /** 编辑：标题/科目/收藏/正文（正文只在显式携带时更新） */
    ArticleVO update(Long userId, String id, ArticleReq req);

    /** 批量审核：ids + auditStatus */
    void batchAudit(Long userId, List<String> ids, Integer auditStatus);

    /** 批量发布/下架：ids + status */
    void batchPublish(Long userId, List<String> ids, Integer status);

    /** 逻辑删除 → 墓碑（随 since 下发手机，design/02 §4） */
    void delete(Long userId, String id);

    void batchDelete(Long userId, List<String> ids);
}
