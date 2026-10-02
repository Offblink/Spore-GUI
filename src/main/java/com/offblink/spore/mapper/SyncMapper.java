package com.offblink.spore.mapper;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.offblink.spore.entity.Article;
import com.offblink.spore.entity.Category;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 同步专用查询（绕过 MP 逻辑删除过滤——pull 必须下发墓碑行，design/02 §4）。
 * XML 见 resources/mapper/SyncMapper.xml（content 列要指定 typeHandler，只能走 XML）。
 */
@Mapper
public interface SyncMapper {

    /** 增量科目（含墓碑 deleted=1），按 update_time 游标升序 */
    List<Category> selectCategoriesSince(@Param("userId") Long userId,
                                         @Param("since") LocalDateTime since,
                                         @Param("limit") int limit);

    /** 增量文章（含墓碑 deleted=1），按 update_time 游标升序 */
    List<Article> selectArticlesSince(@Param("userId") Long userId,
                                      @Param("since") LocalDateTime since,
                                      @Param("limit") int limit);
}
