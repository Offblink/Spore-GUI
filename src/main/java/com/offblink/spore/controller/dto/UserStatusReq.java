package com.offblink.spore.controller.dto;

import javax.validation.constraints.Max;
import javax.validation.constraints.Min;
import javax.validation.constraints.NotNull;

/** 启停用户请求 DTO。 */
public class UserStatusReq {

    @NotNull(message = "状态不能为空")
    @Min(value = 0, message = "状态须为0或1")
    @Max(value = 1, message = "状态须为0或1")
    private Integer status;

    public Integer getStatus() {
        return status;
    }

    public void setStatus(Integer status) {
        this.status = status;
    }
}
