package com.offblink.spore.service.impl;

import com.offblink.spore.common.BizException;
import com.offblink.spore.common.ErrorCode;
import com.offblink.spore.entity.SysConfig;
import com.offblink.spore.mapper.SysConfigMapper;
import com.offblink.spore.service.StorageService;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.file.FileVisitResult;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.SimpleFileVisitor;
import java.nio.file.StandardCopyOption;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.HashMap;
import java.util.Map;

/**
 * 题库目录实现（handoff §2 切换迁移协议）：
 * copy → 校验(文件数+字节数) → 切配置 → 删旧；任一步失败留在旧目录、配置不动。
 * 配置优先级：sys_config(storage_dir) > application.yml spore.storage.data-dir。
 */
@Service
public class StorageServiceImpl implements StorageService {

    private static final String KEY_STORAGE_DIR = "storage_dir";

    private final SysConfigMapper sysConfigMapper;
    private final String configuredDefault;

    public StorageServiceImpl(SysConfigMapper sysConfigMapper,
                              @Value("${spore.storage.data-dir}") String dataDir) {
        this.sysConfigMapper = sysConfigMapper;
        this.configuredDefault = dataDir;
    }

    @Override
    public String currentDir() {
        SysConfig cfg = sysConfigMapper.selectById(KEY_STORAGE_DIR);
        String dir = (cfg == null) ? configuredDefault : cfg.getValue();
        if (dir == null || dir.trim().isEmpty()) {
            dir = configuredDefault;
        }
        return Paths.get(dir).toAbsolutePath().normalize().toString();
    }

    @Override
    public Map<String, Object> info() {
        Path dir = Paths.get(currentDir());
        long[] stat = stat(dir);
        Map<String, Object> m = new HashMap<String, Object>();
        m.put("path", dir.toString());
        m.put("fileCount", stat[0]);
        m.put("bytes", stat[1]);
        return m;
    }

    @Override
    public Map<String, Object> switchTo(String targetPath) {
        if (targetPath == null || targetPath.trim().isEmpty()) {
            throw new BizException(ErrorCode.BAD_REQUEST, "目标目录不能为空");
        }
        Path from = Paths.get(currentDir());
        Path to = Paths.get(targetPath.trim()).toAbsolutePath().normalize();
        if (to.equals(from)) {
            throw new BizException(ErrorCode.BAD_REQUEST, "已是当前目录，无需切换");
        }

        boolean created = false;
        try {
            if (Files.exists(to)) {
                if (!Files.isDirectory(to)) {
                    throw new BizException(ErrorCode.BAD_REQUEST, "目标已存在且不是目录");
                }
                try (java.util.stream.Stream<Path> s = Files.list(to)) {
                    if (s.findAny().isPresent()) {
                        throw new BizException(ErrorCode.BAD_REQUEST, "目标目录非空，为防覆盖已拒绝切换");
                    }
                }
            } else {
                Files.createDirectories(to);
                created = true;
            }

            // 1) copy（全程不动旧目录）
            final long[] src = new long[2]; // [files, bytes]
            if (Files.exists(from)) {
                Files.walkFileTree(from, new SimpleFileVisitor<Path>() {
                    @Override
                    public FileVisitResult preVisitDirectory(Path dir, BasicFileAttributes attrs)
                            throws IOException {
                        Path rel = from.relativize(dir);
                        Path dst = to.resolve(rel);
                        if (!Files.exists(dst)) {
                            Files.createDirectories(dst);
                        }
                        return FileVisitResult.CONTINUE;
                    }

                    @Override
                    public FileVisitResult visitFile(Path file, BasicFileAttributes attrs)
                            throws IOException {
                        Path rel = from.relativize(file);
                        Files.copy(file, to.resolve(rel), StandardCopyOption.REPLACE_EXISTING);
                        src[0]++;
                        src[1] += attrs.size();
                        return FileVisitResult.CONTINUE;
                    }
                });
            }

            // 2) 校验（文件数 + 字节数逐项对拍）
            long[] dst = stat(to);
            if (dst[0] != src[0] || dst[1] != src[1]) {
                cleanup(to, created);
                throw new BizException(ErrorCode.SERVER_ERROR,
                        "迁移校验失败（源 " + src[0] + " 个/" + src[1] + " B，目标 "
                                + dst[0] + " 个/" + dst[1] + " B），已保留原目录");
            }

            // 3) 切配置（此步之后新路径生效）
            put(KEY_STORAGE_DIR, to.toString());

            // 4) 删旧目录（配置已切换，失败只留垃圾不留数据风险）
            if (Files.exists(from)) {
                deleteRecursively(from);
            }

            Map<String, Object> m = new HashMap<String, Object>();
            m.put("path", to.toString());
            m.put("fileCount", dst[0]);
            m.put("bytes", dst[1]);
            return m;
        } catch (BizException e) {
            throw e;
        } catch (IOException e) {
            cleanup(to, created);
            throw new BizException(ErrorCode.SERVER_ERROR, "迁移失败：" + e.getMessage());
        }
    }

    /** 失败清理：只删「本次新建的空目标」；非空目标（用户自己的）不动 */
    private void cleanup(Path to, boolean created) {
        if (!created) {
            return;
        }
        try {
            if (Files.exists(to)) {
                long[] s = stat(to);
                if (s[0] == 0) {
                    Files.deleteIfExists(to);
                }
            }
        } catch (IOException ignored) {
            // 清理失败不影响「留在旧目录」的承诺
        }
    }

    private long[] stat(Path dir) {
        if (!Files.isDirectory(dir)) {
            return new long[]{0, 0};
        }
        final long[] acc = new long[2];
        try {
            Files.walkFileTree(dir, new SimpleFileVisitor<Path>() {
                @Override
                public FileVisitResult visitFile(Path file, BasicFileAttributes attrs) {
                    acc[0]++;
                    acc[1] += attrs.size();
                    return FileVisitResult.CONTINUE;
                }
            });
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
        return acc;
    }

    private void deleteRecursively(Path dir) throws IOException {
        Files.walkFileTree(dir, new SimpleFileVisitor<Path>() {
            @Override
            public FileVisitResult visitFile(Path file, BasicFileAttributes attrs) throws IOException {
                Files.deleteIfExists(file);
                return FileVisitResult.CONTINUE;
            }

            @Override
            public FileVisitResult postVisitDirectory(Path d, IOException exc) throws IOException {
                Files.deleteIfExists(d);
                return FileVisitResult.CONTINUE;
            }
        });
    }

    private void put(String key, String value) {
        SysConfig cfg = sysConfigMapper.selectById(key);
        if (cfg == null) {
            cfg = new SysConfig();
            cfg.setKey(key);
            cfg.setValue(value);
            sysConfigMapper.insert(cfg);
        } else {
            cfg.setValue(value);
            sysConfigMapper.updateById(cfg);
        }
    }
}
