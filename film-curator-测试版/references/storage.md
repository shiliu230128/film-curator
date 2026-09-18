# 存储后端与云端同步

本文件是「数据存在哪里、如何接入飞书或 Notion」的唯一规则来源。表结构定义在 `scripts/film_curator.py` 的 `BACKEND_TEMPLATE`。

## 数据存放方式

飞书或多维表格 / Notion 数据库是影单和观影历史的正本。本地 `data/` 是工作缓存：推荐、画像、计划都在本地算完，再推回云端。

候选池、画像、偏好证据、推荐日志不上云。

## 第一次怎么选

1. 跑 `storage-status`。
2. 若两边都没绑定：问用户要用飞书、Notion，还是给一个现成链接。
3. 只绑定了一边：直接用那一边，不要再问。
4. 两边都绑定且还没记下默认项：问一次以后默认用哪边，用 `storage-default` 记下。

## 自带模板：新建

用户没给链接、要一份新影单时：

1. `backend-template` 拿到列定义、飞书字段和 Notion 属性。
2. 飞书：创建多维表格应用，名称用模板里的 `create_name`（Film Curator 观影记录本）。再建「影单」「观影历史」两张表，字段用 `feishu.watchlist_fields` / `feishu.history_fields`。
3. Notion：创建两个 Database，属性用 `notion.watchlist_properties` / `notion.history_properties`。片名是 title 属性。
4. `storage-bind` 记下链接、应用令牌、表编号。
5. `backend-export` 后把现有记录写入云端。
6. 把访问链接交给用户。

## 用户给了现成链接：绑定并核对

1. `storage-bind --provider ... --watchlist-url ...`（有历史表就一并记下）。
2. 列出云端现有列名，跑 `storage-check-columns`。
3. 缺「本地编号、片名、状态、已删除」（历史表是本地编号、片名、看完日期、已删除）时补上这些必填列。
4. 其他缺的推荐列尽量补；用户原有的额外列保留，不改名、不删除。
5. 再读写记录。

## 同步范围与删除

云端只放正式片单和观影历史。「本地编号」是对账钥匙。删除用「已删除」勾选，不依赖云端真删除接口。

示例数据永不上云。

## 本地命令

前缀 `python3 scripts/film_curator.py` 省略。

| 命令 | 作用 |
|---|---|
| `backend-template` | 输出两张表结构、飞书字段、Notion 属性 |
| `backend-export --output 文件` | 本地影单与历史变成云表形状 |
| `backend-import --input 文件` | 云端拉回写本地 |
| `storage-status` | 已绑定哪边、默认用哪边 |
| `storage-bind` | 记住链接和表编号 |
| `storage-default` | 两边都有时记下默认 |
| `storage-check-columns` | 现有列和模板比一比 |

## AI 执行步骤

### 推送（本地 → 云端）

1. `backend-export --output /tmp/fc_export.json`
2. 查云端现有行，用「本地编号」对上云端记录编号
3. 已有则更新，没有则新增，本地已删则把云端「已删除」勾上
4. 报告新增和更新条数

### 拉取（云端 → 本地）

1. 查出两张表全部记录，写成 `{"watchlist": [...], "history": [...]}` 到 `/tmp/fc_pull.json`
2. `backend-import --input /tmp/fc_pull.json`
3. 报告新增、更新、删除数量

### Notion 对应操作

建两个 Database，Query / Page Create / Page Update。导出导入命令与飞书相同。

## 依赖

飞书用已配置的飞书 MCP；Notion 用 Notion MCP。凭据由用户客户端配置，不写进本项目。飞书没有删除记录接口，所以统一用「已删除」标记。

## 约束

- 云端是正本镜像，不做字段级合并；同时改了以最后一次拉回或推入为准。
- 同步不得绕过 `backend-import` / `backend-export`。
