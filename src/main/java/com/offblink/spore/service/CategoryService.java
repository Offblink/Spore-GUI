package com.offblink.spore.service;

import com.offblink.spore.controller.dto.CategoryNode;
import com.offblink.spore.controller.dto.CategoryReq;

import java.util.List;

/**
 * 分类（科目）服务。交互语义仿 Spore 远端 review 页（0ed3da2/043815e）：
 * 新建=命名即置顶、改名只动名不动成员、删除只解绑成员（文章回未分组）、归属只写字段不动正文。
 * 多级树只在 GUI 呈现（parent_id），手机同步侧平铺（handoff §2）。
 */
public interface CategoryService {

    /** 当前用户科目树（顶层在前，组内按 sort_order；停用的也返回，前端标灰） */
    List<CategoryNode> tree(Long userId);

    /** 新建科目；parentId 空 = 顶层 */
    CategoryNode create(Long userId, CategoryReq req);

    /** 改名/移父级（同步走 LWW，改的就是字段本身） */
    void update(Long userId, String id, CategoryReq req);

    /** 启停（status 0/1） */
    void changeStatus(Long userId, String id, Integer status);

    /** 批量排序：体 [{id, sortOrder}]，只允许同父级内排序 */
    void sort(Long userId, List<CategoryReq.SortItem> items);

    /**
     * 删除科目：逻辑删除墓碑（随 since 下发给手机），
     * 其下文章 category_id 置空回未分组——两端都不允许悬挂引用（design/03 §3）。
     */
    void delete(Long userId, String id);
}
