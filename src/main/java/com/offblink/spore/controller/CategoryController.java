package com.offblink.spore.controller;

import com.offblink.spore.annotation.OpLog;
import com.offblink.spore.annotation.RequirePermission;
import com.offblink.spore.common.R;
import com.offblink.spore.controller.dto.CategoryNode;
import com.offblink.spore.controller.dto.CategoryReq;
import com.offblink.spore.security.UserContext;
import com.offblink.spore.service.CategoryService;
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

/**
 * 分类（科目）接口（design/02 第二节）：
 * 多级树 + 增删改 + 启停 + 批量排序——「内容分类管理 1.5 分」的落点。
 * 交互语义仿 Spore 远端：新建即置顶、改名不动成员、删除只解绑文章。
 */
@RestController
@RequestMapping("/api/categories")
public class CategoryController {

    private final CategoryService categoryService;

    public CategoryController(CategoryService categoryService) {
        this.categoryService = categoryService;
    }

    @GetMapping
    public R<List<CategoryNode>> tree() {
        return R.ok(categoryService.tree(UserContext.getUserId()));
    }

    @PostMapping
    @RequirePermission("category:manage")
    @OpLog("category.create")
    public R<CategoryNode> create(@Valid @RequestBody CategoryReq req) {
        return R.ok(categoryService.create(UserContext.getUserId(), req));
    }

    @PutMapping("/{id}")
    @RequirePermission("category:manage")
    @OpLog("category.update")
    public R<Void> update(@PathVariable("id") String id, @Valid @RequestBody CategoryReq req) {
        categoryService.update(UserContext.getUserId(), id, req);
        return R.ok();
    }

    @PutMapping("/{id}/status")
    @RequirePermission("category:manage")
    @OpLog("category.status")
    public R<Void> changeStatus(@PathVariable("id") String id, @RequestParam Integer status) {
        categoryService.changeStatus(UserContext.getUserId(), id, status);
        return R.ok();
    }

    @PutMapping("/sort")
    @RequirePermission("category:manage")
    @OpLog("category.sort")
    public R<Void> sort(@Valid @RequestBody CategoryReq req) {
        categoryService.sort(UserContext.getUserId(), req.getItems());
        return R.ok();
    }

    @DeleteMapping("/{id}")
    @RequirePermission("category:manage")
    @OpLog("category.delete")
    public R<Void> delete(@PathVariable("id") String id) {
        categoryService.delete(UserContext.getUserId(), id);
        return R.ok();
    }
}
