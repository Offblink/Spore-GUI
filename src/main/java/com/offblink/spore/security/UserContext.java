package com.offblink.spore.security;

/**
 * 登录用户上下文（ThreadLocal）：拦截器塞入，切面/Service 读取，请求结束清空。
 * 一个切面吃两个考点的前提（handoff §3：token 鉴权 + 操作日志同切面族）。
 */
public final class UserContext {

    private static final ThreadLocal<Long> USER_ID = new ThreadLocal<Long>();
    private static final ThreadLocal<Long> ROLE_ID = new ThreadLocal<Long>();

    private UserContext() {
    }

    public static void set(Long userId, Long roleId) {
        USER_ID.set(userId);
        ROLE_ID.set(roleId);
    }

    /** 当前用户 id；未登录返回 null */
    public static Long getUserId() {
        return USER_ID.get();
    }

    /** 当前用户角色 id；未登录返回 null */
    public static Long getRoleId() {
        return ROLE_ID.get();
    }

    public static void clear() {
        USER_ID.remove();
        ROLE_ID.remove();
    }
}
