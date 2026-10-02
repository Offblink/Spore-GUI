package com.offblink.spore.security;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.offblink.spore.common.ErrorCode;
import com.offblink.spore.common.R;
import com.offblink.spore.entity.User;
import com.offblink.spore.mapper.UserMapper;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import java.io.IOException;

/**
 * 登录拦截器：所有 /api/**（除注册/登录）必须带有效的 Authorization: Bearer <token>。
 * 校验通过 → 用户上下文；失败 → 401 + 40101（design/02 统一返回结构）。
 * 手机扫码配对后的连通验证（GET /users/me）也走这里——服务端唯一闸门。
 */
@Component
public class AuthInterceptor implements HandlerInterceptor {

    private final TokenService tokenService;
    private final UserMapper userMapper;
    private final ObjectMapper objectMapper;

    public AuthInterceptor(TokenService tokenService, UserMapper userMapper, ObjectMapper objectMapper) {
        this.tokenService = tokenService;
        this.userMapper = userMapper;
        this.objectMapper = objectMapper;
    }

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler)
            throws IOException {
        String header = request.getHeader("Authorization");
        String token = (header != null && header.startsWith("Bearer ")) ? header.substring(7) : null;
        Long userId = tokenService.verify(token);
        User user = (userId == null) ? null : userMapper.selectById(userId);
        if (user == null) {
            writeUnauthorized(response, "未登录或 token 失效");
            return false;
        }
        if (user.getStatus() != null && user.getStatus() == 0) {
            writeUnauthorized(response, "账号已停用");
            return false;
        }
        UserContext.set(user.getId(), user.getRoleId());
        return true;
    }

    @Override
    public void afterCompletion(HttpServletRequest request, HttpServletResponse response, Object handler,
                                Exception ex) {
        UserContext.clear();
    }

    private void writeUnauthorized(HttpServletResponse response, String message) throws IOException {
        response.setStatus(401);
        response.setContentType("application/json;charset=UTF-8");
        response.getWriter().write(objectMapper.writeValueAsString(R.fail(ErrorCode.UNAUTHORIZED, message)));
    }
}
