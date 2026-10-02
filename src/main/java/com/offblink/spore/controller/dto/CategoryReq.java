package com.offblink.spore.controller.dto;

import javax.validation.constraints.NotBlank;
import javax.validation.constraints.Size;
import java.util.List;

/**
 * 科目入参 DTO。命名口径仿 Spore store.js createSubject：
 * trim 后非空、最长 40——超长/空名一律 40001，两端同一口径。
 */
public class CategoryReq {

    @NotBlank(message = "科目名不能为空")
    @Size(max = 40, message = "科目名最长 40 字")
    private String name;

    /** 父科目 id；空 = 顶层 */
    private String parentId;

    /** 批量排序专用体：[{id, sortOrder}] */
    private List<SortItem> items;

    public static class SortItem {
        private String id;
        private Integer sortOrder;

        public String getId() {
            return id;
        }

        public void setId(String id) {
            this.id = id;
        }

        public Integer getSortOrder() {
            return sortOrder;
        }

        public void setSortOrder(Integer sortOrder) {
            this.sortOrder = sortOrder;
        }
    }

    public String getName() {
        return name;
    }

    public void setName(String name) {
        this.name = name;
    }

    public String getParentId() {
        return parentId;
    }

    public void setParentId(String parentId) {
        this.parentId = parentId;
    }

    public List<SortItem> getItems() {
        return items;
    }

    public void setItems(List<SortItem> items) {
        this.items = items;
    }
}
