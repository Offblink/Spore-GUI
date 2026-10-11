package com.offblink.spore.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.offblink.spore.common.BizException;
import com.offblink.spore.common.ErrorCode;
import com.offblink.spore.controller.dto.ArticleReq;
import com.offblink.spore.controller.dto.ArticleVO;
import com.offblink.spore.controller.dto.PageResult;
import com.offblink.spore.entity.Article;
import com.offblink.spore.entity.Category;
import com.offblink.spore.mapper.ArticleMapper;
import com.offblink.spore.mapper.CategoryMapper;
import com.offblink.spore.model.ArticleContent;
import com.offblink.spore.service.ArticleService;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 文章服务实现。要点：
 * - 科目归属校验：categoryId 必须属于当前用户（挂别人的科目 = 40401）；
 * - 正文整体读写，绝不挑字段（design/03 §2 有损禁令）；
 * - 删除 = 逻辑删除墓碑，行保留供 /sync/pull 下发（design/02 §4）；
 * - 批量操作在事务里逐条执行，任一失败整体回滚（批量处理考点）。
 */
@Service
public class ArticleServiceImpl implements ArticleService {

    private static final DateTimeFormatter SESSION_ID = DateTimeFormatter.ofPattern("yyyyMMdd-HHmmssSSS");

    private final ArticleMapper articleMapper;
    private final CategoryMapper categoryMapper;

    public ArticleServiceImpl(ArticleMapper articleMapper, CategoryMapper categoryMapper) {
        this.articleMapper = articleMapper;
        this.categoryMapper = categoryMapper;
    }

    @Override
    public PageResult<ArticleVO> page(Long userId, int page, int size, String keyword,
                                      String categoryId, String status, Integer fav, String sort) {
        // 条件参数会先于方法求值，null 时不能直接 trim——先归一化再拼条件
        String kw = (keyword == null || keyword.trim().isEmpty()) ? null : keyword.trim();
        String cat = (categoryId == null || categoryId.trim().isEmpty()) ? null : categoryId.trim();
        String st = (status == null || status.trim().isEmpty()) ? null : status.trim();
        LambdaQueryWrapper<Article> qw = new LambdaQueryWrapper<Article>()
                .eq(Article::getUserId, userId)
                .like(kw != null, Article::getTitle, kw)
                .eq(cat != null, Article::getCategoryId, cat)
                .eq(st != null, Article::getStatus, st)
                .eq(fav != null, Article::getFav, fav != null && fav == 1);
        applySort(qw, sort);
        Page<Article> p = articleMapper.selectPage(new Page<Article>(page, size), qw);
        Map<String, String> catNames = categoryNameMap(userId);
        List<ArticleVO> list = new ArrayList<ArticleVO>();
        for (Article a : p.getRecords()) {
            list.add(toVo(a, catNames.get(a.getCategoryId())));
        }
        return new PageResult<ArticleVO>(list, p.getTotal(), page, size);
    }

    @Override
    public ArticleVO get(Long userId, String id) {
        return toVo(requireOwned(userId, id), null);
    }

    @Override
    public ArticleVO create(Long userId, ArticleReq req) {
        Article a = new Article();
        a.setId(newSessionId());
        a.setUserId(userId);
        a.setCategoryId(normalizeCategoryId(userId, req.getCategoryId()));
        a.setTitle(req.getTitle() == null || req.getTitle().trim().isEmpty()
                ? "新会话" : req.getTitle().trim());
        a.setContent(contentOf(req.getMessages()));
        a.setFav(req.getFav() != null && req.getFav() == 1);
        a.setStatus(req.getStatus() == null ? "done" : req.getStatus());
        a.setAuditStatus(req.getAuditStatus() == null ? 1 : req.getAuditStatus());
        a.setOrigin("gui");
        articleMapper.insert(a);
        return toVo(a, null);
    }

    @Override
    public ArticleVO update(Long userId, String id, ArticleReq req) {
        Article a = requireOwned(userId, id);
        if (req.getTitle() != null && !req.getTitle().trim().isEmpty()) {
            a.setTitle(req.getTitle().trim());
        }
        if (req.getCategoryId() != null) {
            // 空串/null 在 DTO 层区分不了「未传」与「移出」——用显式约定：非 null 即重设
            a.setCategoryId(normalizeCategoryId(userId, req.getCategoryId()));
        }
        if (req.getFav() != null) {
            a.setFav(req.getFav() == 1);
        }
        if (req.getStatus() != null) {
            a.setStatus(req.getStatus());
        }
        if (req.getAuditStatus() != null) {
            a.setAuditStatus(req.getAuditStatus());
        }
        if (req.getMessages() != null) {
            a.setContent(contentOf(req.getMessages()));
        }
        // update_time = 同步的 LWW 键 + /sync/pull 的增量游标，必须抬：MetaFillHandler 是
        // strictUpdateFill（字段为 null 才补），实体带着 requireOwned 查出来的旧值 → 桌面的
        // 移入科目/改名/收藏从来没抬过它（2026-10-11 实测：08:28:49 那批 56 次移入全把
        // 08:27:1x 的旧值原样写回，比操作时刻晚 95s）。后果两条：手机端增量 pull 永远看不见
        // 桌面改动；手机随后推送自己更旧的 touched 反而赢 LWW，把桌面刚设的科目冲掉。
        a.setUpdateTime(LocalDateTime.now());
        articleMapper.updateById(a);
        return toVo(a, null);
    }

    @Override
    @Transactional
    public void batchAudit(Long userId, List<String> ids, Integer auditStatus) {
        if (ids == null || ids.isEmpty()) {
            throw new BizException(ErrorCode.BAD_REQUEST, "ids 不能为空");
        }
        if (auditStatus == null) {
            throw new BizException(ErrorCode.BAD_REQUEST, "auditStatus 不能为空");
        }
        for (String id : ids) {
            Article a = requireOwned(userId, id);
            a.setAuditStatus(auditStatus);
            articleMapper.updateById(a);
        }
    }

    @Override
    @Transactional
    public void batchPublish(Long userId, List<String> ids, Integer status) {
        if (ids == null || ids.isEmpty()) {
            throw new BizException(ErrorCode.BAD_REQUEST, "ids 不能为空");
        }
        if (status == null) {
            throw new BizException(ErrorCode.BAD_REQUEST, "status 不能为空");
        }
        for (String id : ids) {
            Article a = requireOwned(userId, id);
            a.setStatus(status == 1 ? "done" : "offline");
            articleMapper.updateById(a);
        }
    }

    @Override
    public void delete(Long userId, String id) {
        requireOwned(userId, id);
        articleMapper.deleteById(id);
    }

    @Override
    @Transactional
    public void batchDelete(Long userId, List<String> ids) {
        if (ids == null || ids.isEmpty()) {
            throw new BizException(ErrorCode.BAD_REQUEST, "ids 不能为空");
        }
        for (String id : ids) {
            requireOwned(userId, id);
            articleMapper.deleteById(id);
        }
    }

    private void applySort(LambdaQueryWrapper<Article> qw, String sort) {
        if ("update_time asc".equalsIgnoreCase(sort)) {
            qw.orderByAsc(Article::getUpdateTime);
        } else if ("created_time desc".equalsIgnoreCase(sort)) {
            qw.orderByDesc(Article::getCreatedTime);
        } else if ("title asc".equalsIgnoreCase(sort)) {
            qw.orderByAsc(Article::getTitle);
        } else {
            qw.orderByDesc(Article::getUpdateTime);
        }
    }

    private Article requireOwned(Long userId, String id) {
        Article a = articleMapper.selectById(id);
        if (a == null || !userId.equals(a.getUserId())) {
            throw new BizException(ErrorCode.NOT_FOUND, "搜题记录不存在");
        }
        return a;
    }

    /** 科目归属校验：不存在/不属于自己 → null（回未分组），不整单拒收 */
    private String normalizeCategoryId(Long userId, String categoryId) {
        if (categoryId == null || categoryId.trim().isEmpty()) {
            return null;
        }
        Category c = categoryMapper.selectById(categoryId.trim());
        if (c == null || !userId.equals(c.getUserId())) {
            return null;
        }
        return c.getId();
    }

    private Map<String, String> categoryNameMap(Long userId) {
        Map<String, String> map = new HashMap<String, String>();
        List<Category> cats = categoryMapper.selectList(
                new LambdaQueryWrapper<Category>().eq(Category::getUserId, userId));
        Set<String> alive = new HashSet<String>();
        for (Category c : cats) {
            alive.add(c.getId());
            map.put(c.getId(), c.getName());
        }
        // 墓碑科目下的旧引用不显示名字（回未分组由删除流程保证，这里是兜底）
        return map;
    }

    private ArticleContent contentOf(List<com.offblink.spore.model.Msg> messages) {
        ArticleContent content = new ArticleContent();
        if (messages != null) {
            content.setMessages(messages);
        }
        return content;
    }

    /** 会话 id 与手机 Session.newId() 同格式（design/03 §1） */
    private String newSessionId() {
        return LocalDateTime.now().format(SESSION_ID);
    }

    private ArticleVO toVo(Article a, String categoryName) {
        ArticleVO vo = new ArticleVO();
        vo.setId(a.getId());
        vo.setCategoryId(a.getCategoryId());
        vo.setCategoryName(categoryName);
        vo.setTitle(a.getTitle());
        vo.setFav(a.getFav() != null && a.getFav() ? 1 : 0);
        vo.setStatus(a.getStatus());
        vo.setAuditStatus(a.getAuditStatus());
        vo.setOrigin(a.getOrigin());
        vo.setAttachmentPath(a.getAttachmentPath());
        if (a.getContent() != null) {
            vo.setMessages(a.getContent().getMessages());
        }
        vo.setCreatedTime(a.getCreatedTime());
        vo.setUpdateTime(a.getUpdateTime());
        return vo;
    }
}
