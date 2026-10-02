package com.offblink.spore.controller.dto;

import javax.validation.constraints.NotNull;

/** 分配角色请求 DTO。 */
public class RoleAssignReq {

    @NotNull(message = "角色Id不能为空")
    private Long roleId;

    public Long getRoleId() {
        return roleId;
    }

    public void setRoleId(Long roleId) {
        this.roleId = roleId;
    }
}
