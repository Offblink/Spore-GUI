package com.offblink.spore.controller;

import com.offblink.spore.annotation.OpLog;
import com.offblink.spore.common.R;
import com.offblink.spore.service.StorageService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 题库目录接口：查询现状 + 切换迁移（handoff §2 协议，设置页消费）。
 * 迁移协议核心：copy → 校验 → 切配置 → 删旧，任一步失败留在旧目录。
 */
@RestController
@RequestMapping("/api/storage")
public class StorageController {

    private final StorageService storageService;

    public StorageController(StorageService storageService) {
        this.storageService = storageService;
    }

    @GetMapping
    public R<Map<String, Object>> info() {
        return R.ok(storageService.info());
    }

    @PutMapping
    @OpLog("storage.switch")
    public R<Map<String, Object>> switchDir(@RequestBody Map<String, String> body) {
        return R.ok(storageService.switchTo(body.get("path")));
    }
}
