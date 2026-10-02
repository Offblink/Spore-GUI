package com.offblink.spore.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.offblink.spore.common.BizException;
import com.offblink.spore.common.ErrorCode;
import com.offblink.spore.controller.dto.LoginReq;
import com.offblink.spore.controller.dto.LoginVO;
import com.offblink.spore.controller.dto.RegisterReq;
import com.offblink.spore.controller.dto.UserVO;
import com.offblink.spore.entity.Role;
import com.offblink.spore.entity.User;
import com.offblink.spore.mapper.RoleMapper;
import com.offblink.spore.mapper.UserMapper;
import com.offblink.spore.security.TokenService;
import com.offblink.spore.service.AuthService;
import com.offblink.spore.service.PermissionService;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;
import java.util.Set;

/**
 * 认证实现：BCrypt 口令哈希（绝不明文）、JWT/LAN token 双通道（见 TokenService）。
 */
@Service
public class AuthServiceImpl implements AuthService {

    private static final BCryptPasswordEncoder ENCODER = new BCryptPasswordEncoder();

    private final UserMapper userMapper;
    private final RoleMapper roleMapper;
    private final TokenService tokenService;
    private final PermissionService permissionService;

    public AuthServiceImpl(UserMapper userMapper, RoleMapper roleMapper, TokenService tokenService,
                           PermissionService permissionService) {
        this.userMapper = userMapper;
        this.roleMapper = roleMapper;
        this.tokenService = tokenService;
        this.permissionService = permissionService;
    }

    @Override
    public Long register(RegisterReq req) {
        String username = req.getUsername().trim();
        Long exists = userMapper.selectCount(
                new LambdaQueryWrapper<User>().eq(User::getUsername, username));
        if (exists != null && exists > 0) {
            throw new BizException(ErrorCode.BAD_REQUEST, "用户名已存在");
        }
        long total = userMapper.selectCount(null);
        // 首个注册者 = 管理员（六表种子只预置角色，用户不预置——口令红线）
        String roleCode = (total == 0) ? "ADMIN" : "USER";
        Role role = roleMapper.selectOne(new LambdaQueryWrapper<Role>().eq(Role::getCode, roleCode));
        if (role == null) {
            throw new BizException(ErrorCode.SERVER_ERROR, "角色数据缺失，请先执行六表 SQL");
        }
        User user = new User();
        user.setUsername(username);
        user.setPassword(ENCODER.encode(req.getPassword()));
        String nickname = req.getNickname();
        user.setNickname((nickname == null || nickname.trim().isEmpty()) ? username : nickname.trim());
        user.setRoleId(role.getId());
        user.setStatus(1);
        userMapper.insert(user);
        if (total == 0) {
            tokenService.bindLanUser(user.getId());
        }
        return user.getId();
    }

    @Override
    public LoginVO login(LoginReq req) {
        User user = userMapper.selectOne(
                new LambdaQueryWrapper<User>().eq(User::getUsername, req.getUsername().trim()));
        if (user == null || !ENCODER.matches(req.getPassword(), user.getPassword())) {
            throw new BizException(ErrorCode.UNAUTHORIZED, "用户名或密码错误");
        }
        if (user.getStatus() != null && user.getStatus() == 0) {
            throw new BizException(ErrorCode.FORBIDDEN, "账号已停用");
        }
        Role role = roleMapper.selectById(user.getRoleId());
        LoginVO vo = new LoginVO();
        vo.setToken(tokenService.issue(user.getId()));
        vo.setUserId(user.getId());
        vo.setUsername(user.getUsername());
        vo.setNickname(user.getNickname());
        vo.setRoleCode(role == null ? null : role.getCode());
        return vo;
    }

    @Override
    public void logout(String token) {
        tokenService.revoke(token);
    }

    @Override
    public UserVO me(Long userId) {
        User user = userMapper.selectById(userId);
        if (user == null) {
            throw new BizException(ErrorCode.UNAUTHORIZED, "用户不存在");
        }
        Role role = roleMapper.selectById(user.getRoleId());
        UserVO vo = new UserVO();
        vo.setId(user.getId());
        vo.setUsername(user.getUsername());
        vo.setNickname(user.getNickname());
        vo.setRoleId(user.getRoleId());
        vo.setRoleName(role == null ? null : role.getName());
        vo.setStatus(user.getStatus());
        vo.setCreatedTime(user.getCreatedTime());
        Set<String> codes = permissionService.codesOfRole(user.getRoleId());
        vo.setPermissions(codes == null ? new ArrayList<String>() : new ArrayList<String>(codes));
        return vo;
    }

    @Override
    public String lanToken() {
        return tokenService.lanToken();
    }

    @Override
    public String createDeviceToken(Long userId) {
        return tokenService.createDeviceToken(userId);
    }

    @Override
    public String deviceLogin(String deviceToken) {
        String jwt = tokenService.deviceLogin(deviceToken);
        if (jwt == null) {
            throw new BizException(ErrorCode.UNAUTHORIZED, "设备令牌无效，请重新登录");
        }
        return jwt;
    }
}
