package com.offblink.spore;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.ConfigurableApplicationContext;

/**
 * Spore 搜题内容管理系统启动类（JFT 课设）。
 * 纯 REST 服务（2026-10-02 换栈定案）：桌面客户端迁到 Python（client/），
 * 本进程只供客户端/手机/ApiFox 走 HTTP——评分主体（SSM/MP/AOP/REST）全在此。
 */
@SpringBootApplication
@MapperScan("com.offblink.spore.mapper")
public class SporeGuiApplication {

    public static void main(String[] args) {
        ConfigurableApplicationContext ctx = SpringApplication.run(SporeGuiApplication.class, args);
        // 阻塞主线程到上下文关闭（保持与 Spring Boot 生命周期一致）
        ctx.registerShutdownHook();
    }
}