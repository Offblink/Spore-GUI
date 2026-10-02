package com.offblink.spore.service;

import com.offblink.spore.controller.dto.LoginReq;
import com.offblink.spore.controller.dto.LoginVO;
import com.offblink.spore.controller.dto.RegisterReq;
import com.offblink.spore.controller.dto.UserVO;

/**
 * 认证与当前用户：注册/登录/退出/个人信息。
 */
public interface AuthService {

    /** 注册；首个注册者自动成为管理员并绑定 LAN token（扫码配对的对端） */
    Long register(RegisterReq req);

    /** 登录，返回含 token 的 VO；用户名或口令错误抛 40101 */
    LoginVO login(LoginReq req);

    /** 作废当前 token */
    void logout(String token);

    /** 当前登录用户信息 + 权限码列表（手机配对的连通验证也走它） */
    UserVO me(Long userId);

    /** LAN token（设置页渲染二维码用） */
    String lanToken();

    /** 轮换并签发本机设备令牌（登录后调用；每次信任动作都换新值，旧值即刻作废） */
    String createDeviceToken(Long userId);

    /** 用设备令牌换普通 JWT；无效/账号停用抛 40101 */
    String deviceLogin(String deviceToken);
}
