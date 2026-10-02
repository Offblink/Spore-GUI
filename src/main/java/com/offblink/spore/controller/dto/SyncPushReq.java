package com.offblink.spore.controller.dto;

import com.offblink.spore.model.Msg;

import java.util.List;

/**
 * 同步上推载荷（design/02 §4）：
 * created/updated = epoch ms（手机 Session 字段风格），服务端转 DATETIME(3) 入库。
 * deleted=1 的条目 = 墓碑（手机删了东西要传播到 PC）。
 */
public class SyncPushReq {

    private List<CategoryItem> categories;
    private List<ArticleItem> articles;

    public static class CategoryItem {
        private String id;
        private String parentId;
        private String name;
        private Integer sortOrder;
        private Integer status;
        private Long created;
        private Long updated;
        private Integer deleted;

        public String getId() {
            return id;
        }

        public void setId(String id) {
            this.id = id;
        }

        public String getParentId() {
            return parentId;
        }

        public void setParentId(String parentId) {
            this.parentId = parentId;
        }

        public String getName() {
            return name;
        }

        public void setName(String name) {
            this.name = name;
        }

        public Integer getSortOrder() {
            return sortOrder;
        }

        public void setSortOrder(Integer sortOrder) {
            this.sortOrder = sortOrder;
        }

        public Integer getStatus() {
            return status;
        }

        public void setStatus(Integer status) {
            this.status = status;
        }

        public Long getCreated() {
            return created;
        }

        public void setCreated(Long created) {
            this.created = created;
        }

        public Long getUpdated() {
            return updated;
        }

        public void setUpdated(Long updated) {
            this.updated = updated;
        }

        public Integer getDeleted() {
            return deleted;
        }

        public void setDeleted(Integer deleted) {
            this.deleted = deleted;
        }
    }

    public static class ArticleItem {
        private String id;
        private String categoryId;
        private String title;
        private List<Msg> messages;
        private Integer fav;
        private String status;
        private Integer auditStatus;
        private String attachmentPath;
        private Long created;
        private Long updated;
        private Integer deleted;

        public String getId() {
            return id;
        }

        public void setId(String id) {
            this.id = id;
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

        public List<Msg> getMessages() {
            return messages;
        }

        public void setMessages(List<Msg> messages) {
            this.messages = messages;
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

        public String getAttachmentPath() {
            return attachmentPath;
        }

        public void setAttachmentPath(String attachmentPath) {
            this.attachmentPath = attachmentPath;
        }

        public Long getCreated() {
            return created;
        }

        public void setCreated(Long created) {
            this.created = created;
        }

        public Long getUpdated() {
            return updated;
        }

        public void setUpdated(Long updated) {
            this.updated = updated;
        }

        public Integer getDeleted() {
            return deleted;
        }

        public void setDeleted(Integer deleted) {
            this.deleted = deleted;
        }
    }

    public List<CategoryItem> getCategories() {
        return categories;
    }

    public void setCategories(List<CategoryItem> categories) {
        this.categories = categories;
    }

    public List<ArticleItem> getArticles() {
        return articles;
    }

    public void setArticles(List<ArticleItem> articles) {
        this.articles = articles;
    }
}
