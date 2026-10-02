package com.offblink.spore.controller;

import com.offblink.spore.annotation.OpLog;
import com.offblink.spore.annotation.RequirePermission;
import com.offblink.spore.common.R;
import com.offblink.spore.controller.dto.ArticleReq;
import com.offblink.spore.controller.dto.ArticleVO;
import com.offblink.spore.controller.dto.PageResult;
import com.offblink.spore.security.UserContext;
import com.offblink.spore.service.ArticleService;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import javax.validation.Valid;
import java.util.List;
import java.util.Map;

/**
 * 文章（搜题记录）接口（design/02 第三节）：
 * 分页多条件检索 + CRUD + 批量审核/发布/删除。手机与 GUI 消费同一套。
 */
@RestController
@RequestMapping("/api/articles")
public class ArticleController {

    private final ArticleService articleService;

    public ArticleController(ArticleService articleService) {
        this.articleService = articleService;
    }

    @GetMapping
    public R<PageResult<ArticleVO>> page(@RequestParam(defaultValue = "1") int page,
                                         @RequestParam(defaultValue = "10") int size,
                                         @RequestParam(required = false) String keyword,
                                         @RequestParam(required = false) String categoryId,
                                         @RequestParam(required = false) String status,
                                         @RequestParam(required = false) Integer fav,
                                         @RequestParam(defaultValue = "update_time desc") String sort) {
        return R.ok(articleService.page(UserContext.getUserId(), page, Math.min(size, 200),
                keyword, categoryId, status, fav, sort));
    }

    @GetMapping("/{id}")
    public R<ArticleVO> get(@PathVariable("id") String id) {
        return R.ok(articleService.get(UserContext.getUserId(), id));
    }

    @PostMapping
    @RequirePermission("article:create")
    @OpLog("article.create")
    public R<ArticleVO> create(@Valid @RequestBody ArticleReq req) {
        return R.ok(articleService.create(UserContext.getUserId(), req));
    }

    @PutMapping("/{id}")
    @RequirePermission("article:edit")
    @OpLog("article.update")
    public R<ArticleVO> update(@PathVariable("id") String id, @Valid @RequestBody ArticleReq req) {
        return R.ok(articleService.update(UserContext.getUserId(), id, req));
    }

    @PostMapping("/batch/audit")
    @RequirePermission("article:audit")
    @OpLog("article.batchAudit")
    public R<Void> batchAudit(@RequestBody Map<String, Object> body) {
        @SuppressWarnings("unchecked")
        List<String> ids = (List<String>) body.get("ids");
        Integer auditStatus = (Integer) body.get("audit_status");
        articleService.batchAudit(UserContext.getUserId(), ids, auditStatus);
        return R.ok();
    }

    @PostMapping("/batch/publish")
    @RequirePermission("article:edit")
    @OpLog("article.batchPublish")
    public R<Void> batchPublish(@RequestBody Map<String, Object> body) {
        @SuppressWarnings("unchecked")
        List<String> ids = (List<String>) body.get("ids");
        Integer status = (Integer) body.get("status");
        articleService.batchPublish(UserContext.getUserId(), ids, status);
        return R.ok();
    }

    @DeleteMapping("/{id}")
    @RequirePermission("article:delete")
    @OpLog("article.delete")
    public R<Void> delete(@PathVariable("id") String id) {
        articleService.delete(UserContext.getUserId(), id);
        return R.ok();
    }

    @PostMapping("/batch/delete")
    @RequirePermission("article:delete")
    @OpLog("article.batchDelete")
    public R<Void> batchDelete(@RequestBody Map<String, Object> body) {
        @SuppressWarnings("unchecked")
        List<String> ids = (List<String>) body.get("ids");
        articleService.batchDelete(UserContext.getUserId(), ids);
        return R.ok();
    }
}
