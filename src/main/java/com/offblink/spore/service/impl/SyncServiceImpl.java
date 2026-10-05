package com.offblink.spore.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.offblink.spore.common.BizException;
import com.offblink.spore.common.ErrorCode;
import com.offblink.spore.controller.dto.SyncPushReq;
import com.offblink.spore.entity.Article;
import com.offblink.spore.entity.Category;
import com.offblink.spore.mapper.ArticleMapper;
import com.offblink.spore.mapper.CategoryMapper;
import com.offblink.spore.mapper.SyncMapper;
import com.offblink.spore.model.ArticleContent;
import com.offblink.spore.model.Msg;
import com.offblink.spore.service.SyncService;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 同步实现。判据与边界（design/02 §4）：
 * - LWW：客户端 updated(epoch ms) > 服务端 update_time 才覆盖，否则保留服务端；
 * - 墓碑：deleted=1 双向传播，行不真删；pull 用 SyncMapper 绕过逻辑删除过滤；
 * - 引用完整性：push 先落 categories 再落 articles；悬空 category_id → 置 NULL（accepted:true + 警告）；
 * - 游标：nextCursor = 本批最大 update_time（毫秒），同毫秒多行靠 limit 分批推进。
 */
@Service
public class SyncServiceImpl implements SyncService {

    private static final int LIMIT_MAX = 500;
    private static final ZoneId ZONE = ZoneId.of("Asia/Shanghai");

    private final SyncMapper syncMapper;
    private final CategoryMapper categoryMapper;
    private final ArticleMapper articleMapper;

    public SyncServiceImpl(SyncMapper syncMapper, CategoryMapper categoryMapper, ArticleMapper articleMapper) {
        this.syncMapper = syncMapper;
        this.categoryMapper = categoryMapper;
        this.articleMapper = articleMapper;
    }

    @Override
    public Map<String, Object> pull(Long userId, long cursor, int limit) {
        if (cursor < 0) {
            throw new BizException(ErrorCode.BAD_REQUEST, "cursor 非法");
        }
        int capped = Math.min(Math.max(limit, 1), LIMIT_MAX);
        LocalDateTime since = toDateTime(cursor);

        List<Category> cats = syncMapper.selectCategoriesSince(userId, since, capped);
        List<Article> arts = syncMapper.selectArticlesSince(userId, since, capped);

        long maxCat = 0L;
        List<Map<String, Object>> catOut = new ArrayList<Map<String, Object>>();
        for (Category c : cats) {
            catOut.add(categoryPayload(c));
            maxCat = Math.max(maxCat, toMillis(c.getUpdateTime()));
        }
        long maxArt = 0L;
        List<Map<String, Object>> artOut = new ArrayList<Map<String, Object>>();
        for (Article a : arts) {
            artOut.add(articlePayload(a));
            maxArt = Math.max(maxArt, toMillis(a.getUpdateTime()));
        }

        // nextCursor = 本批两类里的最大 update_time（都取毫秒，谁大取谁）。
        // 但任一类被 limit 截断（本批没下发完）时，游标不得超过该类的本批最大值——
        // 否则另一类把游标越级抬走，截断类里 >max 的行会被 `> cursor` 永久跳过（同步不全的一条腿）。
        boolean catsHit = cats.size() >= capped;
        boolean artsHit = arts.size() >= capped;
        long nextCursor;
        if (catsHit || artsHit) {
            long cap = Long.MAX_VALUE;
            if (catsHit) {
                cap = Math.min(cap, maxCat);
            }
            if (artsHit) {
                cap = Math.min(cap, maxArt);
            }
            nextCursor = Math.max(cursor, cap);
        } else {
            nextCursor = Math.max(cursor, Math.max(maxCat, maxArt));
        }

        Map<String, Object> data = new LinkedHashMap<String, Object>();
        data.put("categories", catOut);   // 先 categories 后 articles（引用完整性）
        data.put("articles", artOut);
        data.put("nextCursor", nextCursor);
        return data;
    }

    @Override
    @Transactional
    public Map<String, Object> push(Long userId, SyncPushReq req) {
        List<Map<String, Object>> results = new ArrayList<Map<String, Object>>();

        // 第一段：categories（引用完整性——文章引用的科目必须先在）
        if (req.getCategories() != null) {
            for (SyncPushReq.CategoryItem item : req.getCategories()) {
                boolean accepted = mergeCategory(userId, item);
                results.add(resultOf(item.getId(), accepted));
            }
        }
        // 第二段：articles
        if (req.getArticles() != null) {
            for (SyncPushReq.ArticleItem item : req.getArticles()) {
                boolean accepted = mergeArticle(userId, item);
                results.add(resultOf(item.getId(), accepted));
            }
        }

        Map<String, Object> data = new LinkedHashMap<String, Object>();
        data.put("results", results);
        return data;
    }

    /**
     * 题图路径写回（实体更新：非 null 字段才进 SET，update_time 由 MetaFillHandler 抬——
     * 其它端靠增量 pull 看到新路径）。带 user_id 作用域，防跨用户写。
     */
    @Override
    public void bindAttachment(Long userId, String articleId, String path) {
        Article upd = new Article();
        upd.setAttachmentPath(path);
        LambdaUpdateWrapper<Article> w = new LambdaUpdateWrapper<Article>();
        w.eq(Article::getId, articleId).eq(Article::getUserId, userId);
        articleMapper.update(upd, w);
    }

    private boolean mergeCategory(Long userId, SyncPushReq.CategoryItem item) {
        if (item.getId() == null || item.getId().trim().isEmpty()) {
            return false;
        }
        Category local = syncMapper.selectCategoryByIdAny(item.getId());
        if (local == null) {
            Category c = new Category();
            c.setId(item.getId());
            c.setUserId(userId);
            c.setParentId(item.getParentId());
            c.setName(item.getName() == null ? "未命名科目" : item.getName());
            c.setSortOrder(item.getSortOrder() == null ? 0 : item.getSortOrder());
            c.setStatus(item.getStatus() == null ? 1 : item.getStatus());
            // created/update_time 由手机时间戳直接指定（游标语义不能被服务器时钟覆盖）
            c.setCreatedTime(toDateTime(item.getCreated()));
            c.setUpdateTime(toDateTime(item.getUpdated()));
            c.setDeleted(item.getDeleted() != null && item.getDeleted() == 1 ? 1 : 0);
            categoryMapper.insert(c);
            return true;
        }
        if (!lwwWins(item.getUpdated(), local.getUpdateTime())) {
            return false; // 服务端新，保留服务端
        }
        if (item.getParentId() != null && item.getParentId().equals(item.getId())) {
            return false;
        }
        local.setParentId(item.getParentId());
        if (item.getName() != null && !item.getName().trim().isEmpty()) {
            local.setName(item.getName().trim());
        }
        if (item.getSortOrder() != null) {
            local.setSortOrder(item.getSortOrder());
        }
        if (item.getStatus() != null) {
            local.setStatus(item.getStatus());
        }
        local.setUpdateTime(toDateTime(item.getUpdated()));
        local.setDeleted(item.getDeleted() != null && item.getDeleted() == 1 ? 1 : 0);
        categoryMapper.updateById(local);
        return true;
    }

    private boolean mergeArticle(Long userId, SyncPushReq.ArticleItem item) {
        if (item.getId() == null || item.getId().trim().isEmpty()) {
            return false;
        }
        // 必须看得见墓碑行：MP selectById 滤掉 deleted=1 → 误判不存在 → INSERT 撞主键 500
        Article local = syncMapper.selectByIdAny(item.getId());
        if (local == null) {
            Article a = new Article();
            a.setId(item.getId());
            a.setUserId(userId);
            a.setCategoryId(categoryExists(userId, item.getCategoryId()));
            a.setTitle(item.getTitle() == null || item.getTitle().trim().isEmpty()
                    ? "新会话" : item.getTitle().trim());
            a.setContent(contentOf(item.getMessages()));
            a.setFav(item.getFav() != null && item.getFav() == 1);
            a.setStatus(item.getStatus() == null ? "done" : item.getStatus());
            a.setAuditStatus(item.getAuditStatus() == null ? 2 : item.getAuditStatus()); // 手机自答默认通过
            a.setOrigin("mobile");
            a.setAttachmentPath(item.getAttachmentPath());
            a.setCreatedTime(toDateTime(item.getCreated()));
            a.setUpdateTime(toDateTime(item.getUpdated()));
            a.setDeleted(item.getDeleted() != null && item.getDeleted() == 1 ? 1 : 0);
            articleMapper.insert(a);
            return true;
        }
        if (!lwwWins(item.getUpdated(), local.getUpdateTime())) {
            return false;
        }
        if (item.getCategoryId() != null) {
            a_setCategory(local, userId, item.getCategoryId());
        }
        if (item.getTitle() != null && !item.getTitle().trim().isEmpty()) {
            local.setTitle(item.getTitle().trim());
        }
        if (item.getMessages() != null) {
            local.setContent(contentOf(item.getMessages()));
        }
        if (item.getFav() != null) {
            local.setFav(item.getFav() == 1);
        }
        if (item.getStatus() != null) {
            local.setStatus(item.getStatus());
        }
        if (item.getAuditStatus() != null) {
            local.setAuditStatus(item.getAuditStatus());
        }
        if (item.getAttachmentPath() != null) {
            local.setAttachmentPath(item.getAttachmentPath());
        }
        local.setUpdateTime(toDateTime(item.getUpdated()));
        local.setDeleted(item.getDeleted() != null && item.getDeleted() == 1 ? 1 : 0);
        articleMapper.updateById(local);
        return true;
    }

    /** 悬空科目 → 置 NULL 回未分组（accepted:true，不整批拒收） */
    private void a_setCategory(Article a, Long userId, String categoryId) {
        a.setCategoryId(categoryExists(userId, categoryId));
    }

    private String categoryExists(Long userId, String categoryId) {
        if (categoryId == null || categoryId.trim().isEmpty()) {
            return null;
        }
        Category c = categoryMapper.selectById(categoryId.trim());
        return (c != null && userId.equals(c.getUserId())) ? c.getId() : null;
    }

    /** LWW：客户端 updated 比服务端 update_time 新才胜（同毫秒保留服务端，避免抖动） */
    private boolean lwwWins(Long clientUpdated, LocalDateTime serverTime) {
        if (clientUpdated == null || serverTime == null) {
            return false;
        }
        return clientUpdated > toMillis(serverTime);
    }

    private Map<String, Object> categoryPayload(Category c) {
        Map<String, Object> m = new HashMap<String, Object>();
        m.put("id", c.getId());
        m.put("parentId", c.getParentId());
        m.put("name", c.getName());
        m.put("sortOrder", c.getSortOrder());
        m.put("status", c.getStatus());
        m.put("created", toMillis(c.getCreatedTime()));
        m.put("updated", toMillis(c.getUpdateTime()));
        m.put("deleted", c.getDeleted() == null ? 0 : c.getDeleted());
        return m;
    }

    private Map<String, Object> articlePayload(Article a) {
        Map<String, Object> m = new HashMap<String, Object>();
        m.put("id", a.getId());
        m.put("categoryId", a.getCategoryId());
        m.put("title", a.getTitle());
        m.put("messages", a.getContent() == null ? new ArrayList<Msg>() : a.getContent().getMessages());
        m.put("fav", a.getFav() != null && a.getFav() ? 1 : 0);
        m.put("status", a.getStatus());
        m.put("auditStatus", a.getAuditStatus());
        m.put("attachmentPath", a.getAttachmentPath());
        m.put("created", toMillis(a.getCreatedTime()));
        m.put("updated", toMillis(a.getUpdateTime()));
        m.put("deleted", a.getDeleted() == null ? 0 : a.getDeleted());
        return m;
    }

    private Map<String, Object> resultOf(String id, boolean accepted) {
        Map<String, Object> r = new HashMap<String, Object>();
        r.put("id", id);
        r.put("accepted", accepted);
        return r;
    }

    private ArticleContent contentOf(List<Msg> messages) {
        ArticleContent content = new ArticleContent();
        if (messages != null) {
            content.setMessages(messages);
        }
        return content;
    }

    private LocalDateTime toDateTime(Long epochMs) {
        if (epochMs == null) {
            return null;
        }
        return LocalDateTime.ofInstant(Instant.ofEpochMilli(epochMs), ZONE);
    }

    private long toMillis(LocalDateTime time) {
        if (time == null) {
            return 0L;
        }
        return time.atZone(ZONE).toInstant().toEpochMilli();
    }
}
