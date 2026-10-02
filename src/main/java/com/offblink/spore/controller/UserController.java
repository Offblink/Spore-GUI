package com.offblink.spore.controller;

import com.offblink.spore.annotation.OpLog;
import com.offblink.spore.annotation.RequirePermission;
import com.offblink.spore.common.R;
import com.offblink.spore.controller.dto.PageResult;
import com.offblink.spore.controller.dto.RoleAssignReq;
import com.offblink.spore.controller.dto.UserStatusReq;
import com.offblink.spore.controller.dto.UserVO;
import com.offblink.spore.security.UserContext;
import com.offblink.spore.service.AuthService;
import com.offblink.spore.service.UserService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import javax.validation.Valid;

/**
 * 用户管理接口（design/02 第一节）：
 * 分页列表/角色分配/启停——AOP 权限校验考点的主战场。
 */
@RestController
@RequestMapping("/api/users")
public class UserController {

    private final UserService userService;
    private final AuthService authService;

    public UserController(UserService userService, AuthService authService) {
        this.userService = userService;
        this.authService = authService;
    }

    /** 当前登录用户 + 权限码；手机扫码配对后用它验证连通性（design/02 认证节），无权限要求 */
    @GetMapping("/me")
    public R<UserVO> me() {
        return R.ok(authService.me(UserContext.getUserId()));
    }

    @GetMapping
    @RequirePermission("user:manage")
    public R<PageResult<UserVO>> page(@RequestParam(defaultValue = "1") int page,
                                      @RequestParam(defaultValue = "10") int size) {
        return R.ok(userService.page(page, Math.min(size, 200)));
    }

    @PutMapping("/{id}/role")
    @RequirePermission("user:manage")
    @OpLog("user.role")
    public R<Void> assignRole(@PathVariable("id") Long id,
                              @Valid @RequestBody RoleAssignReq req) {
        userService.assignRole(id, req, UserContext.getUserId());
        return R.ok();
    }

    @PutMapping("/{id}/status")
    @RequirePermission("user:manage")
    @OpLog("user.status")
    public R<Void> changeStatus(@PathVariable("id") Long id,
                                @Valid @RequestBody UserStatusReq req) {
        userService.changeStatus(id, req, UserContext.getUserId());
        return R.ok();
    }
}
