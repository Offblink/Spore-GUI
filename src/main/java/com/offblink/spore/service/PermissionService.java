package com.offblink.spore.service;

import java.util.Set;

/**
 * 权限查询：角色 → 权限码集合（PermissionAspect 消费）。
 */
public interface PermissionService {

    /** 角色拥有的全部权限码；带进程内缓存 */
    Set<String> codesOfRole(Long roleId);

    /** 角色是否拥有指定权限码 */
    boolean hasPermission(Long roleId, String code);
}
