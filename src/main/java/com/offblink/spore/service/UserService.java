package com.offblink.spore.service;

import com.offblink.spore.controller.dto.PageResult;
import com.offblink.spore.controller.dto.RoleAssignReq;
import com.offblink.spore.controller.dto.UserStatusReq;
import com.offblink.spore.controller.dto.UserVO;

/**
 * 用户管理（design/02 第一节）：分页列表/角色分配/启停。
 */
public interface UserService {

    PageResult<UserVO> page(int page, int size);

    void assignRole(Long targetId, RoleAssignReq req, Long currentUserId);

    void changeStatus(Long targetId, UserStatusReq req, Long currentUserId);
}
