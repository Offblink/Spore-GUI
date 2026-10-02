package com.offblink.spore.security;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.offblink.spore.entity.SysConfig;
import com.offblink.spore.mapper.SysConfigMapper;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.SignatureAlgorithm;
import io.jsonwebtoken.security.Keys;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import javax.annotation.PostConstruct;
import javax.crypto.SecretKey;
import java.security.SecureRandom;
import java.util.Date;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

/**
 * token 签发/校验（评分表三·数据安全：运行时生成，源码零硬编码）。
 *
 * 两类 token，同一 Bearer 头承载：
 * 1. 登录 JWT：密钥每次启动 SecureRandom 生成（重启即全部失效，单机课设可接受）；
 * 2. LAN token：扫码配对分发给手机（design/02 认证节），首启生成后持久化进
 *    sys_config(lan_token) 并绑定首个注册的管理员——手机扫一次永久有效。
 * 源码与文档中只有 CHANGE_ME/占位，绝不出现真实密钥。
 */
@Service
public class TokenService {

    private static final String KEY_LAN_TOKEN = "lan_token";
    private static final String KEY_LAN_UID = "lan_token_uid";
    /** 本机设备令牌（桌面静默登录）：持久化在 sys_config，源码零硬编码 */
    private static final String KEY_DEVICE_TOKEN = "device_token";
    private static final String KEY_DEVICE_UID = "device_token_uid";
    /** 运行时生成的 JWT 签名密钥（每次启动不同） */
    private static final SecretKey JWT_KEY = Keys.secretKeyFor(SignatureAlgorithm.HS256);
    /** 作废的 JWT jti（logout）；仅本进程内存，重启随 JWT_KEY 一起失效 */
    private static final Set<String> REVOKED = ConcurrentHashMap.newKeySet();

    @Value("${spore.jwt.expire-hours:720}")
    private long expireHours;

    private final SysConfigMapper sysConfigMapper;
    private volatile String lanToken;
    private volatile Long lanTokenUserId;

    public TokenService(SysConfigMapper sysConfigMapper) {
        this.sysConfigMapper = sysConfigMapper;
    }

    @PostConstruct
    public void init() {
        lanToken = get(KEY_LAN_TOKEN);
        if (lanToken == null || lanToken.isEmpty()) {
            lanToken = randomHex(24);
            put(KEY_LAN_TOKEN, lanToken);
        }
        String uid = get(KEY_LAN_UID);
        lanTokenUserId = (uid == null || uid.isEmpty()) ? null : Long.valueOf(uid);
    }

    /** 签发登录 token（绑定当前用户，过期时间见配置） */
    public String issue(Long userId) {
        long now = System.currentTimeMillis();
        return Jwts.builder()
                .setId(UUID.randomUUID().toString())
                .setSubject(String.valueOf(userId))
                .setIssuedAt(new Date(now))
                .setExpiration(new Date(now + expireHours * 3600_000L))
                .signWith(JWT_KEY)
                .compact();
    }

    /**
     * 校验 Bearer token，返回用户 id；无效/过期/已作废返回 null。
     * LAN token 命中则返回其绑定的管理员（扫码配对路径）。
     */
    public Long verify(String token) {
        if (token == null || token.isEmpty()) {
            return null;
        }
        if (token.equals(lanToken)) {
            return lanTokenUserId;
        }
        try {
            Claims claims = Jwts.parserBuilder()
                    .setSigningKey(JWT_KEY)
                    .build()
                    .parseClaimsJws(token)
                    .getBody();
            if (REVOKED.contains(claims.getId())) {
                return null;
            }
            return Long.valueOf(claims.getSubject());
        } catch (JwtException | IllegalArgumentException e) {
            return null;
        }
    }

    /** 作废登录 token（logout） */
    public void revoke(String token) {
        try {
            Claims claims = Jwts.parserBuilder()
                    .setSigningKey(JWT_KEY)
                    .build()
                    .parseClaimsJws(token)
                    .getBody();
            REVOKED.add(claims.getId());
        } catch (JwtException | IllegalArgumentException ignored) {
            // 非法 token 本来就过不了校验，无需作废
        }
    }

    /** LAN token 绑定首个管理员（首注册时调用，之后不再改绑） */
    public synchronized void bindLanUser(Long userId) {
        if (lanTokenUserId != null) {
            return;
        }
        lanTokenUserId = userId;
        put(KEY_LAN_UID, String.valueOf(userId));
    }

    /** LAN token 本体（设置页渲染二维码用） */
    public String lanToken() {
        return lanToken;
    }

    /**
     * 轮换并签发本机设备令牌：持久化进 sys_config，绑定当前用户。
     * 每次「信任本机」动作都换新值——旧文件即刻失效，可远程「踢掉」本机记住的状态。
     */
    public synchronized String createDeviceToken(Long userId) {
        String token = randomHex(24);
        put(KEY_DEVICE_TOKEN, token);
        put(KEY_DEVICE_UID, String.valueOf(userId));
        return token;
    }

    /**
     * 设备令牌 → 普通 JWT 的兑换。令牌无效/绑定用户失效返回 null（调用方转 40101）。
     * 换出来的仍是普通 JWT（同一签名通道）——AOP/拦截器完全无感知，权限模型零改动。
     */
    public String deviceLogin(String deviceToken) {
        if (deviceToken == null || deviceToken.isEmpty()) {
            return null;
        }
        String stored = get(KEY_DEVICE_TOKEN);
        if (stored == null || !stored.equals(deviceToken)) {
            return null;
        }
        String uid = get(KEY_DEVICE_UID);
        if (uid == null || uid.isEmpty()) {
            return null;
        }
        return issue(Long.valueOf(uid));
    }

    private String get(String key) {
        SysConfig cfg = sysConfigMapper.selectById(key);
        return cfg == null ? null : cfg.getValue();
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

    private static String randomHex(int bytes) {
        byte[] buf = new byte[bytes];
        new SecureRandom().nextBytes(buf);
        StringBuilder sb = new StringBuilder(buf.length * 2);
        for (byte b : buf) {
            sb.append(String.format("%02x", b));
        }
        return sb.toString();
    }
}
