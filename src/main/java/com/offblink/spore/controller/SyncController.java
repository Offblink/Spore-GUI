package com.offblink.spore.controller;

import com.offblink.spore.common.R;
import com.offblink.spore.controller.dto.SyncPushReq;
import com.offblink.spore.security.UserContext;
import com.offblink.spore.service.StorageService;
import com.offblink.spore.service.SyncService;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 同步接口（design/02 §四，手机端专用）：
 * pull 游标增量（含墓碑）→ push LWW → 题图按需上/下推。
 * 所有请求都过 AuthInterceptor——未配对（无 token）一律 40101，服务端唯一闸门。
 */
@RestController
@RequestMapping("/api/sync")
public class SyncController {

    private final SyncService syncService;
    private final StorageService storageService;

    public SyncController(SyncService syncService, StorageService storageService) {
        this.syncService = syncService;
        this.storageService = storageService;
    }

    private java.nio.file.Path storageDir() {
        return java.nio.file.Paths.get(storageService.currentDir());
    }

    @GetMapping("/pull")
    public R<Map<String, Object>> pull(@RequestParam(defaultValue = "0") long cursor,
                                       @RequestParam(defaultValue = "200") int limit) {
        return R.ok(syncService.pull(UserContext.getUserId(), cursor, limit));
    }

    @PostMapping("/push")
    public R<Map<String, Object>> push(@RequestBody SyncPushReq req) {
        return R.ok(syncService.push(UserContext.getUserId(), req));
    }

    /** 手机推题图：存题库目录，文件名 = articleId（扩展名保底 .img），路径写回 article 行 */
    @PostMapping(value = "/push-attachment", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public R<Map<String, String>> pushAttachment(@RequestParam String articleId,
                                                 @RequestParam("file") MultipartFile file)
            throws IOException {
        if (file.isEmpty()) {
            return R.fail(40001, "文件为空");
        }
        String safeId = articleId.replaceAll("[^0-9A-Za-z\\-_]", "");
        if (safeId.isEmpty()) {
            return R.fail(40001, "articleId 非法");
        }
        Path dir = storageDir();
        Files.createDirectories(dir);
        String ext = extensionOf(file.getOriginalFilename());
        Path target = dir.resolve(safeId + ext);
        // 先写临时文件再原子移动——半途失败不毁已有题图
        Path tmp = dir.resolve(safeId + ext + ".part");
        file.transferTo(tmp);
        Files.move(tmp, target, StandardCopyOption.REPLACE_EXISTING);
        Map<String, String> data = new LinkedHashMap<String, String>();
        data.put("path", dir.relativize(target).toString());
        // 路径写回 article 行（注释宣称但此前缺失的一步）：桌面端行先建后推图靠它落 path；
        // 手机端先推图后推行时行不存在，0 行匹配无害，路径随后续行 push 带回
        syncService.bindAttachment(UserContext.getUserId(), safeId, data.get("path"));
        return R.ok(data);
    }

    /** 拉题图：按相对路径读盘（路径穿越防护：normalize 后必须仍在题库目录内） */
    @GetMapping("/pull-attachment")
    public ResponseEntity<byte[]> pullAttachment(@RequestParam String path) throws IOException {
        Path resolved = storageDir().resolve(path).normalize();
        if (!resolved.startsWith(storageDir()) || !Files.isRegularFile(resolved)) {
            return ResponseEntity.notFound().build();
        }
        byte[] bytes = Files.readAllBytes(resolved);
        return ResponseEntity.ok()
                .contentType(MediaType.IMAGE_JPEG)
                .body(bytes);
    }

    private String extensionOf(String filename) {
        if (filename == null) {
            return ".img";
        }
        int dot = filename.lastIndexOf('.');
        return (dot >= 0 && dot < filename.length() - 1) ? filename.substring(dot) : ".img";
    }
}
