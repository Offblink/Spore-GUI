package com.offblink.spore.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.offblink.spore.common.BizException;
import com.offblink.spore.common.ErrorCode;
import com.offblink.spore.controller.dto.CategoryNode;
import com.offblink.spore.controller.dto.CategoryReq;
import com.offblink.spore.entity.Article;
import com.offblink.spore.entity.Category;
import com.offblink.spore.mapper.ArticleMapper;
import com.offblink.spore.mapper.CategoryMapper;
import com.offblink.spore.service.CategoryService;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.security.SecureRandom;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * 科目服务实现。
 *
 * id 生成：时间戳 + 4 位随机后缀（字符串 id，两端同一命名空间，handoff §1 禁自增）。
 * 删除语义（design/03 §3 三处统一）：本表留墓碑，其下文章 category_id 置空回未分组。
 * 多级防环：移父级时沿目标祖先链上溯，遇到自己即拒（40001）。
 */
@Service
public class CategoryServiceImpl implements CategoryService {

    private static final DateTimeFormatter ID_TS = DateTimeFormatter.ofPattern("yyyyMMdd-HHmmssSSS");
    private static final SecureRandom RANDOM = new SecureRandom();

    private final CategoryMapper categoryMapper;
    private final ArticleMapper articleMapper;

    public CategoryServiceImpl(CategoryMapper categoryMapper, ArticleMapper articleMapper) {
        this.categoryMapper = categoryMapper;
        this.articleMapper = articleMapper;
    }

    @Override
    public List<CategoryNode> tree(Long userId) {
        List<Category> all = categoryMapper.selectList(new LambdaQueryWrapper<Category>()
                .eq(Category::getUserId, userId)
                .orderByAsc(Category::getSortOrder)
                .orderByDesc(Category::getCreatedTime));
        Map<String, CategoryNode> nodeMap = new HashMap<String, CategoryNode>();
        for (Category c : all) {
            nodeMap.put(c.getId(), toNode(c));
        }
        List<CategoryNode> roots = new ArrayList<CategoryNode>();
        for (Category c : all) {
            CategoryNode node = nodeMap.get(c.getId());
            CategoryNode parent = (c.getParentId() == null) ? null : nodeMap.get(c.getParentId());
            if (parent == null) {
                roots.add(node);
            } else {
                parent.getChildren().add(node);
            }
        }
        return roots;
    }

    @Override
    public CategoryNode create(Long userId, CategoryReq req) {
        String parentId = normalizeParent(req.getParentId());
        if (parentId != null) {
            requireOwned(userId, parentId);
        }
        Category c = new Category();
        c.setId(newId());
        c.setUserId(userId);
        c.setParentId(parentId);
        c.setName(req.getName().trim());
        // 置顶语义（仿 Spore：创建越早越靠上）——新科目 sortOrder 最小
        Long count = categoryMapper.selectCount(new LambdaQueryWrapper<Category>()
                .eq(Category::getUserId, userId));
        c.setSortOrder((count == null ? 0L : count) > Integer.MAX_VALUE ? 0 : count.intValue());
        c.setStatus(1);
        categoryMapper.insert(c);
        return toNode(c);
    }

    @Override
    public void update(Long userId, String id, CategoryReq req) {
        Category c = requireOwned(userId, id);
        if (req.getName() != null && !req.getName().trim().isEmpty()) {
            c.setName(req.getName().trim());
        }
        String newParent = normalizeParent(req.getParentId());
        if (req.getParentId() != null && !req.getParentId().equals(c.getParentId())) {
            if (id.equals(newParent)) {
                throw new BizException(ErrorCode.BAD_REQUEST, "父级不能是自己");
            }
            if (newParent != null) {
                requireOwned(userId, newParent);
                if (isDescendantOf(userId, newParent, id)) {
                    throw new BizException(ErrorCode.BAD_REQUEST, "不能移到自己的子树下");
                }
            }
            c.setParentId(newParent);
        }
        categoryMapper.updateById(c);
    }

    @Override
    public void changeStatus(Long userId, String id, Integer status) {
        Category c = requireOwned(userId, id);
        c.setStatus(status != null && status == 1 ? 1 : 0);
        categoryMapper.updateById(c);
    }

    @Override
    public void sort(Long userId, List<CategoryReq.SortItem> items) {
        if (items == null || items.isEmpty()) {
            throw new BizException(ErrorCode.BAD_REQUEST, "排序列表不能为空");
        }
        for (CategoryReq.SortItem item : items) {
            Category c = requireOwned(userId, item.getId());
            if (item.getSortOrder() != null) {
                c.setSortOrder(item.getSortOrder());
                categoryMapper.updateById(c);
            }
        }
    }

    @Override
    @Transactional
    public void delete(Long userId, String id) {
        requireOwned(userId, id);
        // 墓碑：MP 全局逻辑删除（logic-delete-field=deleted）→ UPDATE deleted=1，行保留供 since 下发
        categoryMapper.deleteById(id);
        // 其下文章回未分组——只改字段+updated 戳，不动正文（handoff §2 科目=字段原则）
        articleMapper.update(null, new LambdaUpdateWrapper<Article>()
                .set(Article::getCategoryId, null)
                .eq(Article::getCategoryId, id));
    }

    private Category requireOwned(Long userId, String id) {
        Category c = categoryMapper.selectById(id);
        if (c == null || !userId.equals(c.getUserId())) {
            throw new BizException(ErrorCode.NOT_FOUND, "科目不存在");
        }
        return c;
    }

    /** 目标节点是否在 id 的子树内（防环） */
    private boolean isDescendantOf(Long userId, String targetId, String id) {
        String cursor = targetId;
        int guard = 0;
        while (cursor != null && guard++ < 64) {
            if (cursor.equals(id)) {
                return true;
            }
            Category c = categoryMapper.selectById(cursor);
            cursor = (c == null) ? null : c.getParentId();
        }
        return false;
    }

    private String normalizeParent(String parentId) {
        if (parentId == null || parentId.trim().isEmpty()) {
            return null;
        }
        return parentId.trim();
    }

    /**
     * 字符串 id：毫秒时间戳 + 4 位随机（与手机 Session.newId() 同风格、同命名空间）。
     * 两端撞号概率：毫秒级时间戳 + 36^4 随机后缀，单人使用下可忽略。
     */
    private String newId() {
        String ts = LocalDateTime.now().format(ID_TS);
        StringBuilder sb = new StringBuilder(ts).append('-');
        for (int i = 0; i < 4; i++) {
            sb.append(Character.forDigit(RANDOM.nextInt(36), 36));
        }
        return sb.toString();
    }

    private CategoryNode toNode(Category c) {
        CategoryNode node = new CategoryNode();
        node.setId(c.getId());
        node.setParentId(c.getParentId());
        node.setName(c.getName());
        node.setSortOrder(c.getSortOrder());
        node.setStatus(c.getStatus());
        return node;
    }
}
