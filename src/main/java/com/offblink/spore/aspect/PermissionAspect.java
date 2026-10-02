package com.offblink.spore.aspect;

import com.offblink.spore.annotation.RequirePermission;
import com.offblink.spore.common.ErrorCode;
import com.offblink.spore.common.BizException;
import com.offblink.spore.security.UserContext;
import com.offblink.spore.service.PermissionService;
import org.aspectj.lang.annotation.Aspect;
import org.aspectj.lang.annotation.Before;
import org.springframework.stereotype.Component;

/**
 * 权限校验切面（评分表二·Spring AOP 接口权限校验 2 分）：
 * 拦 @RequirePermission 标注的接口，按角色-权限表校验，不符抛 40301。
 */
@Aspect
@Component
public class PermissionAspect {

    private final PermissionService permissionService;

    public PermissionAspect(PermissionService permissionService) {
        this.permissionService = permissionService;
    }

    @Before(value = "@annotation(rp)", argNames = "rp")
    public void check(RequirePermission rp) {
        Long roleId = UserContext.getRoleId();
        if (roleId == null) {
            throw new BizException(ErrorCode.UNAUTHORIZED, "未登录");
        }
        if (!permissionService.hasPermission(roleId, rp.value())) {
            throw new BizException(ErrorCode.FORBIDDEN, "无权限：" + rp.value());
        }
    }
}
