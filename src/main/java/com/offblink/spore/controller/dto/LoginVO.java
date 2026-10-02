package com.offblink.spore.controller.dto;

/** 登录响应 VO：token + 用户基础信息。 */
public class LoginVO {

    /** 登录令牌 */
    private String token;

    private Long userId;

    private String username;

    private String nickname;

    /** 角色标识 ADMIN/USER */
    private String roleCode;

    public String getToken() {
        return token;
    }

    public void setToken(String token) {
        this.token = token;
    }

    public Long getUserId() {
        return userId;
    }

    public void setUserId(Long userId) {
        this.userId = userId;
    }

    public String getUsername() {
        return username;
    }

    public void setUsername(String username) {
        this.username = username;
    }

    public String getNickname() {
        return nickname;
    }

    public void setNickname(String nickname) {
        this.nickname = nickname;
    }

    public String getRoleCode() {
        return roleCode;
    }

    public void setRoleCode(String roleCode) {
        this.roleCode = roleCode;
    }
}
