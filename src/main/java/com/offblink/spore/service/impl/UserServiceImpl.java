package com.offblink.spore.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.offblink.spore.common.BizException;
import com.offblink.spore.common.ErrorCode;
import com.offblink.spore.controller.dto.PageResult;
import com.offblink.spore.controller.dto.RoleAssignReq;
import com.offblink.spore.controller.dto.UserStatusReq;
import com.offblink.spore.controller.dto.UserVO;
import com.offblink.spore.entity.Role;
import com.offblink.spore.entity.User;
import com.offblink.spore.mapper.RoleMapper;
import com.offblink.spore.mapper.UserMapper;
import com.offblink.spore.service.UserService;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.stream.Collectors;

/**
 * 用户管理实现。防锁死护栏：不能改自己的角色/停用自己的账号
 * （唯一管理员把自己降级后将无人能进用户管理页）。
 */
@Service
public class UserServiceImpl implements UserService {

    private final UserMapper userMapper;
    private final RoleMapper roleMapper;

    public UserServiceImpl(UserMapper userMapper, RoleMapper roleMapper) {
        this.userMapper = userMapper;
        this.roleMapper = roleMapper;
    }

    @Override
    public PageResult<UserVO> page(int page, int size) {
        Page<User> p = userMapper.selectPage(new Page<User>(page, size),
                new LambdaQueryWrapper<User>().orderByDesc(User::getId));
        List<UserVO> list = p.getRecords().stream().map(this::toVo).collect(Collectors.toList());
        return new PageResult<UserVO>(list, p.getTotal(), page, size);
    }

    @Override
    public void assignRole(Long targetId, RoleAssignReq req, Long currentUserId) {
        if (targetId.equals(currentUserId)) {
            throw new BizException(ErrorCode.BAD_REQUEST, "不能修改自己的角色");
        }
        User target = requireUser(targetId);
        Role role = roleMapper.selectById(req.getRoleId());
        if (role == null) {
            throw new BizException(ErrorCode.NOT_FOUND, "角色不存在");
        }
        target.setRoleId(role.getId());
        userMapper.updateById(target);
    }

    @Override
    public void changeStatus(Long targetId, UserStatusReq req, Long currentUserId) {
        if (targetId.equals(currentUserId)) {
            throw new BizException(ErrorCode.BAD_REQUEST, "不能停用自己的账号");
        }
        User target = requireUser(targetId);
        target.setStatus(req.getStatus());
        userMapper.updateById(target);
    }

    private User requireUser(Long id) {
        User user = userMapper.selectById(id);
        if (user == null) {
            throw new BizException(ErrorCode.NOT_FOUND, "用户不存在");
        }
        return user;
    }

    private UserVO toVo(User user) {
        UserVO vo = new UserVO();
        vo.setId(user.getId());
        vo.setUsername(user.getUsername());
        vo.setNickname(user.getNickname());
        vo.setRoleId(user.getRoleId());
        Role role = roleMapper.selectById(user.getRoleId());
        vo.setRoleName(role == null ? null : role.getName());
        vo.setStatus(user.getStatus());
        vo.setCreatedTime(user.getCreatedTime());
        return vo;
    }
}
