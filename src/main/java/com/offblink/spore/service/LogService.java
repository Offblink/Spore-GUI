package com.offblink.spore.service;

/**
 * 操作日志：LogAspect 调用，落 op_log 表。
 */
public interface LogService {

    void record(Long userId, String action, String target, String detail, String ip);
}
