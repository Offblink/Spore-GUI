package com.offblink.spore.config;

import com.zaxxer.hikari.HikariDataSource;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.jdbc.DataSourceProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.datasource.init.ScriptUtils;

import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.sql.Statement;

/**
 * 首启自动建库：库不存在就建库、缺表就建表、缺角色/权限就播种，全程幂等、绝不 DROP。
 *
 * <p>为什么挂在 {@code DataSource} bean 的工厂方法里：HikariCP 默认
 * {@code initializationFailTimeout=1ms}，bean 一建就急着连库——库不在场直接
 * {@code Exception during pool initialization} → Spring 上下文取消 → JVM 退出。
 * 建库必须发生在 Hikari 拿到连接<b>之前</b>，而工厂方法体正好是那个唯一能插队的时机：
 * 方法体跑完（建库+播种），返回的 HikariDataSource 才会被 MyBatis/业务拿去用。
 * 换成 ApplicationRunner / @PostConstruct 都太晚——那时上下文已经崩了。
 *
 * <p>{@code CREATE DATABASE IF NOT EXISTS} + {@code CREATE TABLE IF NOT EXISTS} +
 * {@code INSERT IGNORE}（配唯一键）三重幂等：升级版本、重装客户端、二次启动都不会
 * 清掉用户已有的搜题记录。要清空重来得手动跑 docs/schema.sql（先 DROP 后建）。
 *
 * <p>用户表故意不播种（口令红线：绝不预置账号），首个注册者由 register() 赋 ADMIN 角色。
 */
@Configuration
public class DatabaseBootstrapConfig {

    private static final Logger LOG = LoggerFactory.getLogger(DatabaseBootstrapConfig.class);

    private static final String JDBC_PREFIX = "jdbc:mysql://";
    /** 建库/建表脚本：打进 jar 的 classpath 资源（schema-init.sql，幂等版） */
    private static final String INIT_SCRIPT = "schema-init.sql";

    /**
     * 自建 DataSource：先确保库与表就位，再把控制权交给 Hikari。
     * 取代 Spring Boot 的自动装配（@ConditionalOnMissingBean(DataSource) 会让位）。
     */
    @Bean
    public DataSource dataSource(DataSourceProperties properties) {
        String url = properties.getUrl();
        String username = properties.determineUsername();
        String password = properties.determinePassword();

        JdbcTarget target = JdbcTarget.parse(url);
        if (target != null) {
            createDatabaseIfAbsent(target, username, password);
            runInitScript(target.toJdbcUrl(), username, password);
        } else {
            // 解析不出库名（如 H2 内存库等非 MySQL 地址）→ 不越权建库，交回原逻辑
            LOG.warn("数据源地址不是 jdbc:mysql://host:port/db 形态，跳过自动建库：{}", url);
        }

        return properties.initializeDataSourceBuilder()
                .type(HikariDataSource.class)
                .build();
    }

    /** 连到 MySQL 服务端（不选库），CREATE DATABASE IF NOT EXISTS。 */
    private void createDatabaseIfAbsent(JdbcTarget target, String username, String password) {
        String serverUrl = target.toServerUrl();
        // 库名白名单：只许字母数字下划线，防拼接注入（虽来自本机配置，仍守一道）
        String db = target.database.replaceAll("[^A-Za-z0-9_]", "");
        if (db.isEmpty()) {
            LOG.warn("库名为空，跳过自动建库");
            return;
        }
        String sql = "CREATE DATABASE IF NOT EXISTS `" + db
                + "` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci";
        try (Connection conn = DriverManager.getConnection(serverUrl, username, password);
             Statement st = conn.createStatement()) {
            st.execute(sql);
            LOG.info("数据库 {} 已就绪（不存在则新建，已存在则保留）", db);
        } catch (SQLException e) {
            throw new IllegalStateException(
                    "自动建库失败：无法用当前账号在 " + serverUrl + " 上执行建库。"
                            + "请确认 MySQL 已启动、账号有建库权限（或先把库建好）。原因：" + e.getMessage(), e);
        }
    }

    /** 对着目标库跑幂等建表+播种脚本。 */
    private void runInitScript(String dbUrl, String username, String password) {
        try (Connection conn = DriverManager.getConnection(dbUrl, username, password)) {
            ScriptUtils.executeSqlScript(conn, new ClassPathResource(INIT_SCRIPT));
            LOG.info("表结构与角色/权限种子已就绪（幂等，缺啥补啥）");
        } catch (SQLException e) {
            throw new IllegalStateException(
                    "自动初始化表结构失败：已连上 " + dbUrl + " 但执行 " + INIT_SCRIPT
                            + " 出错。原因：" + e.getMessage(), e);
        }
    }

    /**
     * 从 {@code jdbc:mysql://host[:port]/db[?params]} 拆出 host:port 与库名，
     * 并能派生出「服务端 URL」（不选库，用于建库）与「库 URL」（用于建表）。
     */
    static final class JdbcTarget {
        final String hostPort;
        final String database;
        final String query;   // 含 ? 的查询串，可能为空

        private JdbcTarget(String hostPort, String database, String query) {
            this.hostPort = hostPort;
            this.database = database;
            this.query = query;
        }

        /** 解析失败（非 MySQL 地址 / 无库名段）返回 null。 */
        static JdbcTarget parse(String url) {
            if (url == null || !url.startsWith(JDBC_PREFIX)) {
                return null;
            }
            String rest = url.substring(JDBC_PREFIX.length());
            int qIdx = rest.indexOf('?');
            String mainPart = (qIdx >= 0) ? rest.substring(0, qIdx) : rest;
            String query = (qIdx >= 0) ? rest.substring(qIdx) : "";
            int slash = mainPart.indexOf('/');
            if (slash < 0) {
                return null;   // 没有库名段（如 jdbc:mysql://localhost:3306/）
            }
            String hostPort = mainPart.substring(0, slash);
            String db = mainPart.substring(slash + 1);
            if (hostPort.isEmpty() || db.isEmpty()) {
                return null;
            }
            return new JdbcTarget(hostPort, db, query);
        }

        /** 服务端 URL：去掉库名，只留 host:port（+原查询串）。 */
        String toServerUrl() {
            return JDBC_PREFIX + hostPort + "/" + query;
        }

        /** 库 URL：host:port/db（+原查询串）。 */
        String toJdbcUrl() {
            return JDBC_PREFIX + hostPort + "/" + database + query;
        }
    }
}
