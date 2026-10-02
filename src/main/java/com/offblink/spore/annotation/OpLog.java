package com.offblink.spore.annotation;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * 操作日志标记（评分表·系统运维「操作日志记录」）。
 * 标在写操作的 Controller 方法上，LogAspect 自动落 op_log 表，不手写日志代码。
 */
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
public @interface OpLog {

    /** 动作标识，如 article.delete / category.create */
    String value();
}
