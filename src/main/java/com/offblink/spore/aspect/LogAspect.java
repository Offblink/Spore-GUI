package com.offblink.spore.aspect;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.offblink.spore.annotation.OpLog;
import com.offblink.spore.common.ErrorCode;
import com.offblink.spore.common.R;
import com.offblink.spore.security.UserContext;
import com.offblink.spore.service.LogService;
import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.annotation.Around;
import org.aspectj.lang.annotation.Aspect;
import org.springframework.stereotype.Component;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;
import org.springframework.web.multipart.MultipartFile;

import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;

/**
 * 操作日志切面（评分表·系统运维「操作日志记录」）：
 * 拦 @OpLog 标注的写操作，业务成功才落 op_log（失败不记，避免脏日志）。
 * 参数序列化进 detail（口令字段在 DTO 上 WRITE_ONLY，天然不会被记走）。
 */
@Aspect
@Component
public class LogAspect {

    private static final int DETAIL_MAX = 500;

    private final LogService logService;
    private final ObjectMapper objectMapper;

    public LogAspect(LogService logService, ObjectMapper objectMapper) {
        this.logService = logService;
        this.objectMapper = objectMapper;
    }

    @Around(value = "@annotation(op)", argNames = "pjp,op")
    public Object around(ProceedingJoinPoint pjp, OpLog op) throws Throwable {
        Object result = pjp.proceed();
        if (result instanceof R && ((R<?>) result).getCode() != ErrorCode.OK) {
            return result;
        }
        try {
            logService.record(UserContext.getUserId(), op.value(),
                    resolveTarget(pjp.getArgs()), serializeDetail(pjp.getArgs()), currentIp());
        } catch (Exception e) {
            // 日志失败不影响业务
        }
        return result;
    }

    /** 首参若是 id（字符串/数字）当作操作对象，便于日志页按对象排查 */
    private String resolveTarget(Object[] args) {
        if (args == null || args.length == 0) {
            return null;
        }
        Object first = args[0];
        if (first instanceof String) {
            String s = ((String) first).trim();
            return s.length() > 128 ? s.substring(0, 128) : s;
        }
        if (first instanceof Number) {
            return String.valueOf(first);
        }
        return null;
    }

    private String serializeDetail(Object[] args) {
        StringBuilder sb = new StringBuilder();
        try {
            for (Object arg : args) {
                if (arg instanceof HttpServletRequest || arg instanceof HttpServletResponse
                        || arg instanceof MultipartFile) {
                    continue;
                }
                if (sb.length() > 0) {
                    sb.append(", ");
                }
                sb.append(objectMapper.writeValueAsString(arg));
            }
        } catch (Exception e) {
            return null;
        }
        String detail = sb.toString();
        return detail.length() > DETAIL_MAX ? detail.substring(0, DETAIL_MAX) : detail;
    }

    private String currentIp() {
        ServletRequestAttributes attrs =
                (ServletRequestAttributes) RequestContextHolder.getRequestAttributes();
        return attrs == null ? null : attrs.getRequest().getRemoteAddr();
    }
}
