package com.offblink.spore.controller;

import com.offblink.spore.annotation.OpLog;
import com.offblink.spore.common.R;
import com.offblink.spore.controller.dto.LoginReq;
import com.offblink.spore.controller.dto.LoginVO;
import com.offblink.spore.controller.dto.RegisterReq;
import com.offblink.spore.service.AuthService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import javax.validation.Valid;

/**
 * 认证接口（design/02 第一节）：注册/登录/退出/当前用户/LAN token。
 * register/login 对外公开（拦截器已排除），其余走登录态。
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

    /** LAN token（扫码配对的载荷）；仅登录后的设置页可取——不登录拿到也过不了 AOP */
    @GetMapping("/lan-token")
    public R<String> lanToken() {
        return R.ok(authService.lanToken());
    }
}
