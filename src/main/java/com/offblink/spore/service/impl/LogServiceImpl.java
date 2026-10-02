package com.offblink.spore.service.impl;

import com.offblink.spore.entity.OpLog;
import com.offblink.spore.mapper.OpLogMapper;
import com.offblink.spore.service.LogService;
import org.springframework.stereotype.Service;

/**
 * 操作日志实现：只增不改（op_log 表无 update_time/deleted）。
 */
@Service
public class LogServiceImpl implements LogService {

    private final OpLogMapper opLogMapper;

    public LogServiceImpl(OpLogMapper opLogMapper) {
        this.opLogMapper = opLogMapper;
    }

    @Override
    public void record(Long userId, String action, String target, String detail, String ip) {
        OpLog log = new OpLog();
        log.setUserId(userId);
        log.setAction(action);
        log.setTarget(target);
        log.setDetail(detail);
        log.setIp(ip);
        opLogMapper.insert(log);
    }
}
