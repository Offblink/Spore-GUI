package com.offblink.spore.common;

/**
 * 统一返回结构：{ code, message, data }（design/02）。
 * code=0 成功；非 0 见 ErrorCode，HTTP 状态由全局异常处理器映射。
 */
public class R<T> {

    private int code;
    private String message;
    private T data;

    public static <T> R<T> ok() {
        return ok(null);
    }

    public static <T> R<T> ok(T data) {
        R<T> r = new R<T>();
        r.code = ErrorCode.OK;
        r.message = "ok";
        r.data = data;
        return r;
    }

    public static <T> R<T> fail(int code, String message) {
        R<T> r = new R<T>();
        r.code = code;
        r.message = message;
        return r;
    }

    public int getCode() {
        return code;
    }

    public void setCode(int code) {
        this.code = code;
    }

    public String getMessage() {
        return message;
    }

    public void setMessage(String message) {
        this.message = message;
    }

    public T getData() {
        return data;
    }

    public void setData(T data) {
        this.data = data;
    }
}
