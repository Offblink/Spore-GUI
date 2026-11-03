package com.offblink.spore.config;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.text.SimpleDateFormat;
import java.util.TimeZone;

/**
 * Jackson 装配——取代 Boot 的 {@code JacksonAutoConfiguration} 与
 * {@code spring.jackson.time-zone / date-format} 两个配置项。
 *
 * <p>口径与 Boot 时代逐条对齐（2026-11-03 起旧 jar 实测基线）：
 * <ul>
 *   <li>{@code LocalDateTime} → ISO 字符串 {@code 2026-11-03T19:30:59}
 *       （关 {@code WRITE_DATES_AS_TIMESTAMPS}，否则变成 {@code [2026,11,3,...]} 数组）；</li>
 *   <li>{@code null} 照常出参（不加 NON_NULL，基线里是 {@code "data":null}）；</li>
 *   <li>未知字段不报错（Jackson2ObjectMapperBuilder 的默认口径，客户端加字段不炸）；</li>
 *   <li>日期字段 {@code yyyy-MM-dd HH:mm:ss.SSS}、时区 Asia/Shanghai。</li>
 * </ul>
 *
 * <p>这个 bean 同时给两处用：消息转换器（WebConfig#extendMessageConverters）和
 * LogAspect 的参数序列化——同一套口径，别各配一个。
 */
@Configuration
public class JacksonConfig {

    @Bean
    public ObjectMapper objectMapper() {
        ObjectMapper mapper = new ObjectMapper();
        // JavaTimeModule 等由 classpath 上的 jackson-* 模块自动注册
        mapper.findAndRegisterModules();
        mapper.disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);
        mapper.disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES);
        mapper.setDateFormat(new SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS"));
        mapper.setTimeZone(TimeZone.getTimeZone("Asia/Shanghai"));
        return mapper;
    }
}
