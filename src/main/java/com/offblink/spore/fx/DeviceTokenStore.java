package com.offblink.spore.fx;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;

/**
 * 本机设备令牌文件（B 方案静默登录）：
 * 位置 = 工作目录 ./device.token（.gitignore 已排除——令牌绝不进 git，评分红线）。
 * 令牌本体由服务端 sys_config 持有并轮换，这里只是本机副本。
 */
public final class DeviceTokenStore {

    private static final Path FILE = Paths.get("device.token").toAbsolutePath().normalize();

    private DeviceTokenStore() {
    }

    /** 读令牌；文件不存在/读失败返回 null（= 未信任过本机，走正常登录页） */
    public static String read() {
        try {
            if (!Files.isRegularFile(FILE)) {
                return null;
            }
            String token = new String(Files.readAllBytes(FILE), StandardCharsets.UTF_8).trim();
            return token.isEmpty() ? null : token;
        } catch (IOException e) {
            return null;
        }
    }

    /** 写令牌（登录成功后轮换取新值，覆盖旧文件） */
    public static void write(String token) {
        try {
            Files.write(FILE, token.getBytes(StandardCharsets.UTF_8),
                    StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING);
        } catch (IOException e) {
            // 写失败只影响下次免登，不阻塞本次使用
        }
    }

    /** 令牌失效（device-login 被拒）时清掉，避免每次启动都白试一次 */
    public static void clear() {
        try {
            Files.deleteIfExists(FILE);
        } catch (IOException ignored) {
        }
    }
}
