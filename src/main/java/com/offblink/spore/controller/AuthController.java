package com.offblink.spore.controller;

import com.offblink.spore.annotation.OpLog;
import com.offblink.spore.common.R;
import com.offblink.spore.controller.dto.LoginReq;
import com.offblink.spore.controller.dto.LoginVO;
import com.offblink.spore.controller.dto.RegisterReq;
import com.offblink.spore.security.UserContext;
import com.offblink.spore.service.AuthService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import javax.validation.Valid;
import java.util.Map;

/**
 * 认证接口（design/02 第一节）：注册/登录/退出/当前用户/LAN token。
 * register/login/device-login 对外公开（拦截器已排除），其余走登录态。
 */
@RestController
@RequestMapping("/api/auth")
public class AuthController {

    private final AuthService authService;

    public AuthController(AuthService authService) {
        this.authService = authService;
    }

    @PostMapping("/register")
    @OpLog("user.register")
    public R<Long> register(@Valid @RequestBody RegisterReq req) {
        return R.ok(authService.register(req));
    }

    @PostMapping("/login")
    @OpLog("user.login")
    public R<LoginVO> login(@Valid @RequestBody LoginReq req) {
        return R.ok(authService.login(req));
    }

    @PostMapping("/logout")
    public R<Void> logout(@RequestHeader(value = "Authorization", required = false) String authorization) {
        if (authorization != null && authorization.startsWith("Bearer ")) {
            authService.logout(authorization.substring(7));
        }
        return R.ok();
    }

    /**
     * LAN token（扫码配对的载荷）；仅登录后的设置页可取——不登录拿到也过不了 AOP。
     * 取用即把 token 改绑到当前登录用户：谁展示二维码，手机就同步谁。
     */
    @GetMapping("/lan-token")
    public R<String> lanToken() {
        return R.ok(authService.lanToken(UserContext.getUserId()));
    }

    /**
     * 签发本机设备令牌（登录后调用）：GUI 拿它存本机，下次启动免输口令。
     * 令牌只存在本机文件（device.token，gitignore）与 sys_config——源码零硬编码。
     */
    @PostMapping("/device-token")
    public R<String> createDeviceToken() {
        return R.ok(authService.createDeviceToken(UserContext.getUserId()));
    }

    /** 设备令牌换 JWT（公开）：桌面启动捷径；换到的还是普通 JWT，权限模型零改动 */
    @PostMapping("/device-login")
    public R<String> deviceLogin(@RequestBody Map<String, String> body) {
        return R.ok(authService.deviceLogin(body.get("deviceToken")));
    }
}
