package com.offblink.spore.common;

/**
 * 业务异常：带业务码，由全局异常处理器统一转成 R 结构 + 对应 HTTP 状态。
 */
public class BizException extends RuntimeException {

    private final int code;

    public BizException(int code, String message) {
        super(message);
        this.code = code;
    }

    public int getCode() {
        return code;
    }
}
