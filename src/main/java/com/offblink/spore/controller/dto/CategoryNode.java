package com.offblink.spore.controller.dto;

import java.util.ArrayList;
import java.util.List;

/**
 * 科目树节点（出参 VO）：多级树只在 GUI 呈现（handoff §2）。
 */
public class CategoryNode {

    private String id;
    private String parentId;
    private String name;
    private Integer sortOrder;
    private Integer status;
    private List<CategoryNode> children = new ArrayList<CategoryNode>();

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

    public List<CategoryNode> getChildren() {
        return children;
    }

    public void setChildren(List<CategoryNode> children) {
        this.children = children;
    }
}
