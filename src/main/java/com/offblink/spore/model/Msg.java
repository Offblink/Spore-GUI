package com.offblink.spore.model;

import com.fasterxml.jackson.databind.JsonNode;

/** 搜题记录中的一条消息（用户/助手/思考/工具调用等，tools 原样透传）。 */
public class Msg {

    /** 消息角色 */
    private String role;

    /** 消息种类 */
    private String kind;

    /** 正文 */
    private String text;

    /** 思考内容 */
    private String think;

    /** 序号 */
    private String no;

    /** 标题 */
    private String title;

    /** 答案 */
    private String ans;

    /** 解释 */
    private String why;

    /** 核验结论 */
    private String verifyVerdict;

    /** 核验备注 */
    private String verifyNote;

    /** 核验思考 */
    private String verifyThink;

    /** 核验流式备注 */
    private String verifyStreamNote;

    /** 题图路径 */
    private String imagePath;

    /** 是否带图 */
    private Boolean hasImage;

    /** 是否已核验 */
    private Boolean verifyRan;

    /** 是否跳过核验 */
    private Boolean verifySkipped;

    /** 核验挂起中 */
    private Boolean verifyPending;

    /** 思考区是否展开 */
    private Boolean thinkOpen;

    /** 工具调用（原样透传） */
    private JsonNode tools;

    /** 时间戳 */
    private Long ts;

    public String getRole() {
        return role;
    }

    public void setRole(String role) {
        this.role = role;
    }

    public String getKind() {
        return kind;
    }

    public void setKind(String kind) {
        this.kind = kind;
    }

    public String getText() {
        return text;
    }

    public void setText(String text) {
        this.text = text;
    }

    public String getThink() {
        return think;
    }

    public void setThink(String think) {
        this.think = think;
    }

    public String getNo() {
        return no;
    }

    public void setNo(String no) {
        this.no = no;
    }

    public String getTitle() {
        return title;
    }

    public void setTitle(String title) {
        this.title = title;
    }

    public String getAns() {
        return ans;
    }

    public void setAns(String ans) {
        this.ans = ans;
    }

    public String getWhy() {
        return why;
    }

    public void setWhy(String why) {
        this.why = why;
    }

    public String getVerifyVerdict() {
        return verifyVerdict;
    }

    public void setVerifyVerdict(String verifyVerdict) {
        this.verifyVerdict = verifyVerdict;
    }

    public String getVerifyNote() {
        return verifyNote;
    }

    public void setVerifyNote(String verifyNote) {
        this.verifyNote = verifyNote;
    }

    public String getVerifyThink() {
        return verifyThink;
    }

    public void setVerifyThink(String verifyThink) {
        this.verifyThink = verifyThink;
    }

    public String getVerifyStreamNote() {
        return verifyStreamNote;
    }

    public void setVerifyStreamNote(String verifyStreamNote) {
        this.verifyStreamNote = verifyStreamNote;
    }

    public String getImagePath() {
        return imagePath;
    }

    public void setImagePath(String imagePath) {
        this.imagePath = imagePath;
    }

    public Boolean getHasImage() {
        return hasImage;
    }

    public void setHasImage(Boolean hasImage) {
        this.hasImage = hasImage;
    }

    public Boolean getVerifyRan() {
        return verifyRan;
    }

    public void setVerifyRan(Boolean verifyRan) {
        this.verifyRan = verifyRan;
    }

    public Boolean getVerifySkipped() {
        return verifySkipped;
    }

    public void setVerifySkipped(Boolean verifySkipped) {
        this.verifySkipped = verifySkipped;
    }

    public Boolean getVerifyPending() {
        return verifyPending;
    }

    public void setVerifyPending(Boolean verifyPending) {
        this.verifyPending = verifyPending;
    }

    public Boolean getThinkOpen() {
        return thinkOpen;
    }

    public void setThinkOpen(Boolean thinkOpen) {
        this.thinkOpen = thinkOpen;
    }

    public JsonNode getTools() {
        return tools;
    }

    public void setTools(JsonNode tools) {
        this.tools = tools;
    }

    public Long getTs() {
        return ts;
    }

    public void setTs(Long ts) {
        this.ts = ts;
    }
}
