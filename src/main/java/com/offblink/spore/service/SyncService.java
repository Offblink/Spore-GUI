package com.offblink.spore.service;

import com.offblink.spore.controller.dto.SyncPushReq;

import java.util.List;
import java.util.Map;

/**
 * 同步服务（design/02 §4，handoff §1）：
 * 游标=update_time 毫秒；LWW（客户端 updated 胜）；删除靠墓碑传播；categories 先于 articles。
 */
public interface SyncService {

    /**
     * 增量下拉：含墓碑。返回 { categories, articles, nextCursor }。
     * cursor 毫秒（缺省 0）；limit 上限 500，超限截断。
     */
    Map<String, Object> pull(Long userId, long cursor, int limit);

    /**
     * 手机上推：逐条 LWW。返回 { results: [{id, accepted}] }。
     * 顺序固定 categories → articles（引用完整性）。
     */
    Map<String, Object> push(Long userId, SyncPushReq req);

    /**
     * 题图落盘后把相对路径写回 article 行并抬 update_time（其它端靠增量 pull 学到新路径）。
     * 手机端可能先推图后推行（行还不存在 → 0 行匹配是常态，路径随后续行 push 带回）；
     * 桌面端行先建后推图，这里必须真写——pushAttachment 端点只负责写文件。
     */
    void bindAttachment(Long userId, String articleId, String path);
}
