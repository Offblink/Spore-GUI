package com.offblink.spore;

import com.offblink.spore.fx.MainStage;
import com.sun.javafx.application.PlatformImpl;
import javafx.application.Platform;
import org.mybatis.spring.annotation.MapperScan;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.ConfigurableApplicationContext;

/**
 * Spore 搜题内容管理系统启动类（JFT 课设）。
 * 单进程内嵌 Tomcat 提供 REST + JavaFX 窗口（handoff §1 定案）：
 * Spring 就绪后再起 JavaFX；关窗不退 JVM（REST 照常服务手机/ApiFox）。
 * JavaFX 侧只经 ApiClient 走 HTTP，不注入 service 不直连 DB。
 */
@SpringBootApplication
@MapperScan("com.offblink.spore.mapper")
public class SporeGuiApplication {

    private static final Logger log = LoggerFactory.getLogger(SporeGuiApplication.class);

    public static void main(String[] args) {
        ConfigurableApplicationContext ctx = SpringApplication.run(SporeGuiApplication.class, args);
        // 启动 JavaFX 工具包（JDK8 的 Platform 无 startup 方法，走 PlatformImpl）；窗口在 FX 线程创建
        Platform.setImplicitExit(false);
        PlatformImpl.startup(() -> {
            try {
                MainStage stage = new MainStage();
                stage.show();
                log.info("JavaFX 窗口已启动（关窗不退出，REST 继续服务）");
            } catch (Exception e) {
                log.error("JavaFX 窗口启动失败，REST 服务不受影响", e);
            }
        });
        // 阻塞主线程到上下文关闭（保持与 Spring Boot 生命周期一致）
        ctx.registerShutdownHook();
    }
}
