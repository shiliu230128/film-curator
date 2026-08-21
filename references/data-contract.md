# 数据契约、同步与导入

本文件是数据字段、状态、导入导出和三层数据同步的唯一规则来源。稳定的校验和迁移由 `scripts/film_curator.py` 与网页端 `web/core.js` 执行。

## 文件职责

- `user_profile.json`：观影频率、类型偏好、情绪与视听偏好、喜欢的创作者和影片、学习权重。
- `watchlist.json`：所有当前记录的统一数据库。
- `candidate_pool.json`：用户随口提到的“可能想看”、Skill 检索到但用户还没采纳的候选。它不是正式片单，不参与统计、状态筛选和画像学习。
- `history.json`：每次完成观影的不可变事件。
- `recommend_log.json`：推荐曝光、采纳、跳过和看完反馈。
- `preference_evidence.json`：可追溯的偏好观察，不等同于已确认的长期画像结论。
- `config.json`：记录本名称、主题、赏析深度、默认排序、周起始日和用户保存的筛选视图。

## 记录字段

必要字段：`id`、`title`、`content_type`、`status`、`added_date`。

`content_type` 只能是 `movie`、`series`、`documentary`、`animation`、`short`。`status` 只能是 `want`、`watching`、`watched`、`dropped`。`plan_period` 为空表示不在计划中，也可以是 `week`、`month`、`season`。`douban_rating`、`user_rating`、`work_rating` 和 `fit_rating` 都是 0-10 的数字；前者是豆瓣网络评分，`work_rating` 是作品评价，`fit_rating` 是当时适配度。新流程优先记录后两个字段，旧的 `user_rating` 保持兼容。

基础信息可使用 `title_en`、`year`、`director`、`actors`、`country_region`、`language`、`duration_min`、`episode_count`、`release_date`、`genres`、`poster_url`。计划可使用 `watch_episodes` 和 `watch_duration_min` 表示剧集本次观看集数与预计时长。用户信息可使用 `favorite`、`priority`、`tags`、`moods`、`synopsis`、`recommend_reason`、`user_comment`、`watched_date`。

外部候选使用 `source_tier=external`，并记录 `source` 和 `candidate_id`。外部候选和库内记录一样，都可以在后续查询中补齐年份、时长、评分、平台等事实字段；没查到的就留空或标未知，不要凭感觉补数。

候选池中的记录可以复用以上基础字段，但不使用 `status` 表示“想看/看过”。候选池只表示“可以考虑”，不是“用户已经加入待看”。用户明确采纳后，再通过 `adopt-candidate` 写入 `watchlist.json`，此时才成为正式待看记录。

`config.app_name` 是页面顶部记录本名称，默认是“你的观影记录本”，可以在网页中修改并写回主数据。`config.field_options.genres` 和 `config.field_options.tags` 保存网页中可管理的影片类型、标签候选项；删除候选项时会同时从全部记录中移除该值。`config.saved_views` 是数组，每个视图包含唯一 `id`、显示名称 `name` 和 `filters`。筛选可包含 `statuses`、`contentType`、`planPeriod`、`favorite`、`minRating`、`genreQuery`。视图只是筛选条件，不存影片副本。网页默认“最爱清单”是 `minRating=9`，默认“已弃”是 `statuses=["dropped"]`；用户可以基于当前筛选另存自己的视图。

## 表格格式

网页 CSV/XLSX 使用中文列头，同时导入兼容对应的英文键名。数组字段（主演、类型、标签、情绪）使用顿号、逗号或分号分隔；“最爱”接受“是/否”、`true/false`、`1/0`。CSV 使用 UTF-8 BOM、RFC 风格双引号转义；XLSX 第一张工作表作为记录表。

禁止新写入 `zone`、`watch_cue`、`planned` 和 `paused`。导入旧数据时把 `planned/paused` 迁移为 `want`，删除旧字段。

## 重复判定

片名先做 NFKC 规范化，再忽略大小写、空白、常见书名号和连接符后比较。同名即进入冲突列表，年份不同也不能静默当成不同作品；必须展示年份、导演等信息供用户选择。

ID 重复与片名重复是两个问题。新增记录必须生成唯一 ID；片名重复由用户选择跳过、并存或更新现有记录。导入默认是新增并去重，不覆盖整个数据库。

## 三层数据

1. `data/*.json` 是权威主数据，供 Codex 和 CLI 读写。
2. `web/data.js` 是主数据的网页快照，由 `export-web` 生成，不单独手工维护。网页第一次需要用户连接项目文件夹；连接后，网页对主数据的修改会直接写回 `data/*.json`，并同步刷新 `web/data.js`。
3. 浏览器只保存“已连接过哪个项目文件夹”的授权记录，不再保存另一份可编辑草稿，也不作为主数据来源。

如果没有连接项目文件夹，网页只读快照，不能真正改写磁盘。运行 CLI 更新主数据后仍然要重新生成 `web/data.js`；网页导出的备份合并回主数据前必须先预检，不能把下载文件当成新的权威来源长期并行维护。

## 导入预检与策略

JSON 读取数组、`{items: [...]}` 或完整 `{watchlist:{items:[...]}}`；网页也读取 CSV、TSV 和 XLSX 第一张工作表。规范化片名，检查缺少片名、与现有影单同名、导入文件内部同名和 ID 冲突。预检完成前不修改数据。

- `skip`（默认）：保留现有同名记录，只新增不重复项。
- `keep`：所有有效记录都新增，为冲突 ID 生成新 ID。
- `replace`：保留现有 ID，用导入字段更新第一条同名记录。

应用前展示数量和重复明细；应用后报告新增、跳过、更新、无效数量，并运行数据校验和网页导出。只有用户明确要求用备份完全恢复时，才允许整体替换。

通过 Skill/脚本导入时，默认会尝试联网补齐客观信息，包括简介、类型、导演、时长、语言、地区、上映日期和英文名。联网失败、没查到或信息不确定时不阻塞导入，字段保持空白或原样。用户明确要求不补全时使用 `--no-enrich`。

如果记录里仍然缺这些客观字段，下次 skill 再触发时会自动重试补全，不需要用户专门发“再补一次”。这条规则同时适用于导入后的待看记录和候选池里的候选。

## 导出格式

- JSON：完整备份，包括画像、记录、历史、配置、自定义视图和推荐日志。
- CSV：只导出统一记录库，使用 UTF-8 BOM。
- XLSX：只导出统一记录库，第一行冻结并启用筛选。

CSV/XLSX 不包含画像和历史事件；完整恢复必须使用 JSON。
