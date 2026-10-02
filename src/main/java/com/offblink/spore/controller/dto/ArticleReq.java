package com.offblink.spore.controller.dto;

import com.offblink.spore.model.Msg;

import javax.validation.constraints.Size;
import java.util.List;

/**
 * 文章入参 DTO。content 只在编辑正文时携带（null = 不动正文，避免半截覆盖）。
 */
public class ArticleReq {

    @Size(max = 200, message = "标题最长 200 字")
    private String title;

    /** 科目 id；null/空 = 未分组 */
    private String categoryId;

    private Integer fav;

    /** 会话状态 done/error/aborted…（同步只推这三种，design/03 §1） */
    private String status;

    private Integer auditStatus;

    /** 正文：messages 数组整体，显式携带才更新 */
    private List<Msg> messages;

    public String getTitle() {
        return title;
    }

    public void setTitle(String title) {
        this.title = title;
    }

    public String getCategoryId() {
        return categoryId;
    }

    public void setCategoryId(String categoryId) {
        this.categoryId = categoryId;
    }

    public Integer getFav() {
        return fav;
    }

    public void setFav(Integer fav) {
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

    public List<Msg> getMessages() {
        return messages;
    }

    public void setMessages(List<Msg> messages) {
        this.messages = messages;
    }
}
