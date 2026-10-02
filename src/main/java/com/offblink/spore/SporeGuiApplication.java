package com.offblink.spore;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * Spore 搜题内容管理系统启动类（JFT 课设）。
 * 单进程内嵌 Tomcat 提供 REST；JavaFX 窗口在 fx 增量中接入（同一 JVM，UI 只走 REST）。
 */
@SpringBootApplication
@MapperScan("com.offblink.spore.mapper")
public class SporeGuiApplication {

    public static void main(String[] args) {
        SpringApplication.run(SporeGuiApplication.class, args);
    }
}
