package com.offblink.spore.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.offblink.spore.entity.Permission;
import com.offblink.spore.mapper.PermissionMapper;
import com.offblink.spore.service.PermissionService;
import org.springframework.stereotype.Service;

import java.util.Collections;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.stream.Collectors;

/**
 * 权限查询实现：permission 表按角色取码，进程内缓存（design/02 AOP 落法）。
 * 课设角色权限固定，缓存无需失效通道；重启即重建。
 */
@Service
public class PermissionServiceImpl implements PermissionService {

    private final PermissionMapper permissionMapper;
    private final Map<Long, Set<String>> cache = new ConcurrentHashMap<Long, Set<String>>();

    public PermissionServiceImpl(PermissionMapper permissionMapper) {
        this.permissionMapper = permissionMapper;
    }

    @Override
    public Set<String> codesOfRole(Long roleId) {
        if (roleId == null) {
            return Collections.emptySet();
        }
        return cache.computeIfAbsent(roleId, id -> permissionMapper
                .selectList(new LambdaQueryWrapper<Permission>().eq(Permission::getRoleId, id))
                .stream()
                .map(Permission::getCode)
                .collect(Collectors.toSet()));
    }

    @Override
    public boolean hasPermission(Long roleId, String code) {
        return codesOfRole(roleId).contains(code);
    }
}
