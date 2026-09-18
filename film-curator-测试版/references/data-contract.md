# 数据契约与同步

本文件是数据字段、状态和云端同步的规则来源。稳定的校验由 `scripts/film_curator.py` 执行。没有本地网页，也没有 JSON/CSV/Excel 文件导入导出。

## 文件职责

- `user_profile.json`：观影频率、类型偏好、情绪与视听偏好、喜欢的创作者和影片、学习权重。不上云。
- `watchlist.json`：正式片单，与飞书/Notion 影单表对账。
- `candidate_pool.json`：随口提到、还没采纳的候选。不上云，不参与统计和画像学习。
- `history.json`：每次看完的事件，与云端观影历史对账。
- `recommend_log.json`：推荐曝光、采纳、跳过。不上云。
- `preference_evidence.json`：可追溯的偏好观察。不上云。
- `config.json`：记录本名称、赏析深度、周起始日、候选项，以及飞书/Notion 绑定（`storage`）。

## 记录字段

必要字段：`id`、`title`、`content_type`、`status`、`added_date`。

`content_type` 只能是 `movie`、`series`、`documentary`、`animation`、`short`。`status` 只能是 `want`、`watching`、`watched`、`dropped`。`plan_period` 为空表示不在计划中，也可以是 `week`、`month`、`season`。

评分：`douban_rating` 是豆瓣分；`work_rating` 是「我的评分」；`fit_rating` 是当时适配度，可选。读取时旧写法 `user_rating`、`作品评价` 仍译到 `work_rating`。

基础信息可用 `title_en`、`year`、`director`、`actors`、`country_region`、`language`、`duration_min`、`episode_count`、`release_date`、`genres`、`poster_url`。用户信息可用 `favorite`、`priority`、`tags`、`moods`、`synopsis`、`recommend_reason`、`user_comment`、`watched_date`。

外部候选使用 `source_tier=external`。没查到的事实字段留空，不要编。

候选池不使用 `status` 表示想看。用户明确采纳后才 `adopt-candidate` 写入正式片单。

禁止新写入 `zone`、`watch_cue`、`planned` 和 `paused`。旧数据里的 `planned/paused` 当作 `want`。

## 重复判定

片名先做 NFKC 规范化，再忽略大小写、空白、书名号和连接符。同名必须展示年份、导演供用户选择，不能静默当成不同作品。

## 云端

规则细节见 `storage.md`。这里只定契约：

- 云端只镜像正式片单和观影历史。
- 表结构唯一来源是 `BACKEND_TEMPLATE`。
- 「本地编号」是对账钥匙。
- 删除用「已删除」标记。
- 示例数据不上云。
- 写入本地后应推回已绑定的云端。
