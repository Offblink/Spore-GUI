package com.offblink.spore.annotation;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * 接口权限校验（评分表二·Spring AOP 接口权限校验 2 分）。
 * 标在 Controller 方法上，PermissionAspect 按 permission.code 拦截。
 */
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
public @interface RequirePermission {

    /** 权限码，如 article:delete / user:manage */
    String value();
}
