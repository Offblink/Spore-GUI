package com.offblink.spore.model;

import java.util.ArrayList;
import java.util.List;

/** 文章内容载体：messages 数组整体落 article.content JSON 列。 */
public class ArticleContent {

    private List<Msg> messages = new ArrayList<>();

    public List<Msg> getMessages() {
        return messages;
    }

    public void setMessages(List<Msg> messages) {
        this.messages = messages;
    }
}
