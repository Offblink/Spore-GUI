package com.offblink.spore.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import java.time.LocalDateTime;

/** 键值配置实体（sys_config 表，辅助非业务表）。 */
@TableName("sys_config")
public class SysConfig {

    @TableId(value = "`key`", type = IdType.INPUT)
    private String key;

    /** 配置值 */
    private String value;

    private LocalDateTime updateTime;

    public String getKey() {
        return key;
    }

    public void setKey(String key) {
        this.key = key;
    }

    public String getValue() {
        return value;
    }

    public void setValue(String value) {
        this.value = value;
    }

    public LocalDateTime getUpdateTime() {
        return updateTime;
    }

    public void setUpdateTime(LocalDateTime updateTime) {
        this.updateTime = updateTime;
    }
}
