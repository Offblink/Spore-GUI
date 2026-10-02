package com.offblink.spore.common;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.validation.FieldError;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import javax.servlet.http.HttpServletResponse;

/**
 * 全局异常处理：任何异常都转成统一 R 结构（design/02），
 * 错误 message 给人看、不泄堆栈；HTTP 状态按业务码映射。
 */
@RestControllerAdvice
public class GlobalExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    @ExceptionHandler(BizException.class)
    public R<Void> handleBiz(BizException e, HttpServletResponse response) {
        response.setStatus(ErrorCode.httpStatus(e.getCode()));
        return R.fail(e.getCode(), e.getMessage());
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public R<Void> handleValid(MethodArgumentNotValidException e, HttpServletResponse response) {
        response.setStatus(400);
        StringBuilder sb = new StringBuilder();
        for (FieldError fe : e.getBindingResult().getFieldErrors()) {
            if (sb.length() > 0) {
                sb.append("; ");
            }
            sb.append(fe.getField()).append(' ').append(fe.getDefaultMessage());
        }
        return R.fail(ErrorCode.BAD_REQUEST, sb.length() == 0 ? "参数校验失败" : sb.toString());
    }

    @ExceptionHandler(HttpMessageNotReadableException.class)
    public R<Void> handleUnreadable(HttpMessageNotReadableException e, HttpServletResponse response) {
        response.setStatus(400);
        return R.fail(ErrorCode.BAD_REQUEST, "请求体格式错误");
    }

    @ExceptionHandler(Exception.class)
    public R<Void> handleOther(Exception e, HttpServletResponse response) {
        log.error("系统异常", e);
        response.setStatus(500);
        return R.fail(ErrorCode.SERVER_ERROR, "系统异常");
    }
}
