package com.offblink.spore.entity;

import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.FieldStrategy;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler;
import com.offblink.spore.model.ArticleContent;
import java.time.LocalDateTime;

/** 文章实体（article 表，搜题记录，content 整体 JSON 落库）。 */
@TableName(value = "article", autoResultMap = true)
public class Article {

    /** 会话 id：yyyyMMdd-HHmmssSSS */
    @TableId(type = IdType.INPUT)
    private String id;

    /** 外键→user */
    private Long userId;

    /**
     * 外键→category；NULL=未分组。
     * updateStrategy=ALWAYS：updateById 默认跳过 null 字段，「移出科目」
     * （set null）会被静默吞掉——2026-10-03 用户「移动到未分组自动失败」根因。
     */
    @TableField(updateStrategy = FieldStrategy.ALWAYS)
    private String categoryId;

    /** 标题 */
    private String title;

    /** messages 数组整体落 JSON */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private ArticleContent content;

    /** 收藏 */
    private Boolean fav;

    /** 会话态 done/error/aborted/… */
    private String status;

    /** 审核流 0草稿 1待审 2通过 3驳回 */
    private Integer auditStatus;

    /** 来源 mobile/gui */
    private String origin;

    /** 题图相对题库目录的路径 */
    private String attachmentPath;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdTime;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updateTime;

    /** 逻辑删除墓碑 0否 1是 */
    private Integer deleted;

    public String getId() {
        return id;
    }

    public void setId(String id) {
        this.id = id;
    }

    public Long getUserId() {
        return userId;
    }

    public void setUserId(Long userId) {
        this.userId = userId;
    }

    public String getCategoryId() {
        return categoryId;
    }

    public void setCategoryId(String categoryId) {
        this.categoryId = categoryId;
    }

    public String getTitle() {
        return title;
    }

    public void setTitle(String title) {
        this.title = title;
    }

    public ArticleContent getContent() {
        return content;
    }

    public void setContent(ArticleContent content) {
        this.content = content;
    }

    public Boolean getFav() {
        return fav;
    }

    public void setFav(Boolean fav) {
        this.fav = fav;
    }

    public String getStatus() {
        return status;
    }

    public void setStatus(String status) {
        this.status = status;
    }

    public Integer getAuditStatus() {
        return auditStatus;
    }

    public void setAuditStatus(Integer auditStatus) {
        this.auditStatus = auditStatus;
    }

    public String getOrigin() {
        return origin;
    }

    public void setOrigin(String origin) {
        this.origin = origin;
    }

    public String getAttachmentPath() {
        return attachmentPath;
    }

    public void setAttachmentPath(String attachmentPath) {
        this.attachmentPath = attachmentPath;
    }

    public LocalDateTime getCreatedTime() {
        return createdTime;
    }

    public void setCreatedTime(LocalDateTime createdTime) {
        this.createdTime = createdTime;
    }

    public LocalDateTime getUpdateTime() {
        return updateTime;
    }

    public void setUpdateTime(LocalDateTime updateTime) {
        this.updateTime = updateTime;
    }

    public Integer getDeleted() {
        return deleted;
    }

    public void setDeleted(Integer deleted) {
        this.deleted = deleted;
    }
}
