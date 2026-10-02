package com.offblink.spore.controller;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.offblink.spore.annotation.RequirePermission;
import com.offblink.spore.common.R;
import com.offblink.spore.controller.dto.PageResult;
import com.offblink.spore.entity.OpLog;
import com.offblink.spore.mapper.OpLogMapper;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 操作日志接口（design/02 第五节）：分页 + action/userId 过滤，log:view 权限。
 * 数据由 LogAspect 自动写入，本 Controller 只读。
 */
@RestController
@RequestMapping("/api/logs")
public class LogController {

    private final OpLogMapper opLogMapper;

    public LogController(OpLogMapper opLogMapper) {
        this.opLogMapper = opLogMapper;
    }

    @GetMapping
    @RequirePermission("log:view")
    public R<PageResult<OpLog>> page(@RequestParam(defaultValue = "1") int page,
                                     @RequestParam(defaultValue = "20") int size,
                                     @RequestParam(required = false) String action,
                                     @RequestParam(required = false) Long userId) {
        LambdaQueryWrapper<OpLog> qw = new LambdaQueryWrapper<OpLog>()
                .eq(action != null && !action.trim().isEmpty(), OpLog::getAction, action)
                .eq(userId != null, OpLog::getUserId, userId)
                .orderByDesc(OpLog::getId);
        Page<OpLog> p = opLogMapper.selectPage(new Page<OpLog>(page, Math.min(size, 200)), qw);
        List<OpLog> list = p.getRecords();
        return R.ok(new PageResult<OpLog>(list, p.getTotal(), page, size));
    }
}
