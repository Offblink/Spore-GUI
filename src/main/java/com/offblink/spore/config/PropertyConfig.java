package com.offblink.spore.config;

import org.springframework.context.support.PropertySourcesPlaceholderConfigurer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.io.ClassPathResource;
import org.springframework.core.io.FileSystemResource;
import org.springframework.core.io.Resource;

import java.util.ArrayList;
import java.util.List;

/**
 * 属性装载——取代 Boot 的 {@code application.yml} + {@code spring.profiles.include=local}
 * + {@code --spring.config.additional-location} 那一套。
 *
 * <p>两处来源，后者覆盖前者：
 * <ol>
 *   <li>{@code classpath:application.properties}：打进 war 的默认值（无口令）；</li>
 *   <li>外部 {@code db.properties}：真实连接信息，只在本机（gitignore），绝不进 war。</li>
 * </ol>
 *
 * <p><b>为什么外部路径要显式指路</b>：客户端装进 Program Files 后 cwd 会迁到可写根
 * （{@code %LOCALAPPDATA%\\Spore}），只按 {@code file:./} 搜工作目录就找不到放在
 * war/exe 旁的口令文件——1.3.1 真机踩过（配置改对了仍 {@code Access denied}）。
 * 于是由客户端传 {@code -Dspore.config=<db.properties 绝对路径>}；开发态直接跑 Tomcat
 * 不给该属性时，回落工作目录 {@code ./db.properties}（仓库根一份，见 db.properties.example）。
 *
 * <p>口令只从文件读，绝不进命令行——argv 在任务管理器里是公开的。
 */
@Configuration
public class PropertyConfig {

    @Bean
    public static PropertySourcesPlaceholderConfigurer placeholders() {
        PropertySourcesPlaceholderConfigurer cfg = new PropertySourcesPlaceholderConfigurer();
        cfg.setIgnoreResourceNotFound(true);
        cfg.setFileEncoding("UTF-8");

        List<Resource> locations = new ArrayList<Resource>();
        locations.add(new ClassPathResource("application.properties"));
        String external = System.getProperty("spore.config", "./db.properties");
        locations.add(new FileSystemResource(external));
        cfg.setLocations(locations.toArray(new Resource[0]));
        return cfg;
    }
}
