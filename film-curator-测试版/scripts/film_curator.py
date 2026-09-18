#!/usr/bin/env python3
"""Deterministic data operations for the Film Curator skill."""

from __future__ import annotations

import argparse
import copy
import html
import json
import math
import os
import re
import sys
import tempfile
import time
import unicodedata
import uuid
from collections import Counter
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable
from urllib.error import URLError, HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / "data"
CONTENT_TYPES = {"movie", "series", "documentary", "animation", "short"}
ALL_STATUSES = {"want", "watching", "watched", "dropped"}
PLAN_PERIODS = {"week", "month", "season"}
PLAN_CAPACITY = {
    "weekly_1": {"week": 1, "month": 4, "season": 12},
    "weekly_2": {"week": 2, "month": 8, "season": 22},
    "monthly_2": {"week": 1, "month": 2, "season": 6},
    "irregular": {"week": 1, "month": 3, "season": 3},
}

PLAN_FLEX_RATIO = {"month": 0.2, "season": 0.1}
METADATA_LOOKUP_TIMEOUT = 8.0
WIKIDATA_API_URL = "https://www.wikidata.org/w/api.php"
WIKIPEDIA_SUMMARY_URL = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}"
DOUBAN_SUGGEST_URL = "https://movie.douban.com/j/subject_suggest"
DOUBAN_SEARCH_URL = "https://www.douban.com/search"
DOUBAN_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# 字段中文化。数据文件里的键名和几类取值默认写成中文，代码内部继续用英文标识符，
# 翻译只发生在 read_json / write_json 这一道。读取时中英文都认，写出时按
# config.json 的 字段语言（field_language）决定，改成 "en" 就写回英文键名。
FIELD_LANGUAGES = ("zh", "en")
DEFAULT_FIELD_LANGUAGE = "zh"

FIELD_NAMES: dict[str, str] = {
    "schema_version": "结构版本",
    "items": "记录",
    "events": "事件",
    "is_example": "示例数据",
    "id": "记录ID",
    "title": "片名",
    "title_en": "英文名",
    "year": "年份",
    "director": "导演",
    "actors": "主演",
    "country_region": "国家地区",
    "language": "语言",
    "genres": "类型",
    "tags": "自定义标签",
    "moods": "情绪",
    "content_type": "内容类型",
    "duration_min": "时长分钟",
    "episode_count": "集数",
    "watch_episodes": "本次看几集",
    "watch_duration_min": "本次预计时长",
    "release_date": "上映日期",
    "douban_rating": "豆瓣评分",
    "work_rating": "我的评分",
    "fit_rating": "当时适配度",
    "status": "状态",
    "favorite": "最爱",
    "plan_period": "计划周期",
    "priority": "优先级",
    "synopsis": "简介",
    "recommend_reason": "推荐理由",
    "user_comment": "我的短评",
    "poster_url": "图片地址",
    "source": "来源",
    "source_tier": "来源层级",
    "candidate_id": "候选ID",
    "added_date": "加入日期",
    "watched_date": "看完日期",
    "strategy_tag": "策略标签",
    # 观影画像
    "frequency": "观影频率",
    "preferred_genres": "偏好类型",
    "avoided_genres": "避开类型",
    "preferred_languages": "偏好语言",
    "avoided_languages": "避开语言",
    "subtitle_mode": "字幕场景",
    "narrative_pace": "叙事节奏",
    "desired_mood": "想要的情绪",
    "av_preference": "视听偏好",
    "favorite_directors": "喜欢的导演",
    "favorite_actors": "喜欢的演员",
    "top_films": "最爱影片",
    "genre_weights": "类型权重",
    "ratings_count": "评分次数",
    "high_ratings_count": "高分次数",
    "last_updated": "最后更新",
    "onboarding_stage": "引导阶段",
    "feedback_prompted_item_ids": "已问过反馈的记录ID",
    # 配置
    "app_name": "记录本名称",
    "theme": "主题",
    "depth_level": "赏析深度",
    "default_sort": "默认排序",
    "week_starts_monday": "周一作为一周开始",
    "field_options": "候选项",
    "saved_views": "自定义视图",
    "filters": "筛选条件",
    "statuses": "状态列表",
    "contentType": "内容类型筛选",
    "planPeriod": "计划周期筛选",
    "minRating": "最低评分",
    "genreQuery": "类型或标签包含",
    "field_language": "字段语言",
    "storage": "云端",
    "provider": "服务",
    "default_provider": "默认服务",
    "watchlist_url": "影单链接",
    "history_url": "历史链接",
    "app_token": "应用令牌",
    "watchlist_table_id": "影单表编号",
    "history_table_id": "历史表编号",
    "watchlist_database_id": "影单库编号",
    "history_database_id": "历史库编号",
    "bound_at": "绑定时间",
    # 历史与日志事件
    "item_id": "对应记录ID",
    "session_id": "会话ID",
    "rating": "评分",
    "comment": "短评",
    "strategy": "策略",
    "feedback": "反馈",
    "feedback_reason": "反馈理由",
    "event_type": "事件类型",
    "date": "日期",
    "scope": "范围",
    "context": "当时情况",
    "signal": "观察到的偏好",
    "related_item": "相关影片",
    "confirmed": "已确认",
    "reason": "理由",
}

# genre_weights 的键是用户自己的类型名，不是字段名，整棵子树原样保留。
OPAQUE_KEYS = frozenset({"genre_weights"})

# 自定义视图里的 id / name 指视图本身，换个更准的叫法。
SUBTREE_FIELD_OVERRIDES: dict[str, dict[str, str]] = {
    "saved_views": {"id": "视图ID", "name": "视图名称"},
}

# 需要连取值一起翻的字段：字段名 -> 取值表
ENUM_FIELDS: dict[str, str] = {
    "content_type": "content_type",
    "status": "status",
    "plan_period": "plan_period",
    "statuses": "status",
    "contentType": "content_type",
    "planPeriod": "plan_period",
}

VALUE_NAMES: dict[str, dict[str, str]] = {
    "content_type": {
        "movie": "电影",
        "series": "剧集",
        "documentary": "纪录片",
        "animation": "动画",
        "short": "短片",
    },
    "status": {"want": "待看", "watching": "在看", "watched": "已看", "dropped": "已弃"},
    "plan_period": {"week": "本周", "month": "本月", "season": "本季"},
}

# 读取时额外认的写法：表格里的表头、旧文档用过的状态词、迁移前的旧状态值。
FIELD_NAME_ALIASES: dict[str, str] = {
    "记录 ID": "id",
    "国家/地区": "country_region",
    "时长（分钟）": "duration_min",
    "标签": "tags",
    "视图ID": "id",
    "视图名称": "name",
    # 评分字段曾经一分为二：旧的 user_rating（我的评分）和后来的 work_rating（作品评价）。
    # 实际使用中两者始终同值，当时适配度从未被填过，区分只存在于规则里。现在合成一个
    # work_rating，对外仍叫「我的评分」。旧文件和旧表格里的两种写法都读进这一个字段。
    "user_rating": "work_rating",
    "作品评价": "work_rating",
}

VALUE_ALIASES: dict[str, dict[str, str]] = {
    "status": {
        "planned": "want",
        "paused": "want",
        "想看": "want",
        "看完": "watched",
        "弃看": "dropped",
    },
}

DEFAULT_FILES: dict[str, dict[str, Any]] = {
    "user_profile.json": {
        "schema_version": 1,
        "frequency": "irregular",
        "preferred_genres": [],
        "avoided_genres": [],
        "preferred_languages": [],
        "avoided_languages": [],
        "narrative_pace": "mood_dependent",
        "desired_mood": [],
        "av_preference": [],
        "favorite_directors": [],
        "favorite_actors": [],
        "top_films": [],
        "genre_weights": {},
        "ratings_count": 0,
        "high_ratings_count": 0,
        "subtitle_mode": "any",
        "last_updated": None,
        "onboarding_stage": "new",
        "feedback_prompted_item_ids": [],
    },
    "watchlist.json": {"schema_version": 1, "items": []},
    "candidate_pool.json": {"schema_version": 1, "items": []},
    "history.json": {"schema_version": 1, "events": []},
    "config.json": {
        "schema_version": 1,
        "app_name": "你的观影记录本",
        "theme": "fresh-light",
        "depth_level": "standard",
        "default_sort": "added_date_desc",
        "week_starts_monday": True,
        "field_language": DEFAULT_FIELD_LANGUAGE,
        "field_options": {
            "genres": ["剧情", "喜剧", "爱情", "悬疑", "犯罪", "科幻", "奇幻", "动画", "纪录片", "惊悚", "家庭", "历史", "战争", "音乐"],
            "tags": ["高分", "经典", "治愈", "慢燃", "摄影", "女性", "成长", "周末", "下饭"],
        },
        "saved_views": [],
        "storage": {
            "default_provider": "",
            "feishu": {},
            "notion": {},
        },
    },
    "recommend_log.json": {"schema_version": 1, "events": []},
    "preference_evidence.json": {"schema_version": 1, "events": []},
}


# 云表字段的中立类型。影单和观影历史这两张表用一套中性类型描述，落到飞书或
# Notion 时各自翻译成自己的字段类型，规则只在这里定义一次。
BACKEND_FIELD_TYPES: dict[str, dict[str, Any]] = {
    "text": {"feishu": 1, "notion": "rich_text"},
    "number": {"feishu": 2, "notion": "number"},
    "single_select": {"feishu": 3, "notion": "select"},
    "multi_select": {"feishu": 4, "notion": "multi_select"},
    "date": {"feishu": 5, "notion": "date"},
    "checkbox": {"feishu": 7, "notion": "checkbox"},
    "url": {"feishu": 15, "notion": "url"},
}

# 云表结构唯一来源。两张表：影单（正式片单）、观影历史（用户的观看记录，最高频
# 场景）。每列标清对应本地字段、中立类型、枚举取值表或列表标记；本地编号是同步时
# 两边对账的钥匙，已删除是云表专用的删除标记列，不落进本地记录字段。
# 候选池不上云：它是「随口提到、还没采纳」的临时记录，多数没有稳定编号，无法对账，
# 同步会重复新增，所以留在本地。
BACKEND_TEMPLATE: dict[str, dict[str, Any]] = {
    "watchlist": {
        "name": "影单",
        "key_field": "id",
        "columns": [
            {"name": "本地编号", "field": "id", "type": "text"},
            {"name": "片名", "field": "title", "type": "text"},
            {"name": "状态", "field": "status", "type": "single_select", "enum": "status"},
            {"name": "内容类型", "field": "content_type", "type": "single_select", "enum": "content_type"},
            {"name": "类型", "field": "genres", "type": "multi_select", "list": True},
            {"name": "自定义标签", "field": "tags", "type": "multi_select", "list": True},
            {"name": "情绪", "field": "moods", "type": "multi_select", "list": True},
            {"name": "我的评分", "field": "work_rating", "type": "number"},
            {"name": "豆瓣评分", "field": "douban_rating", "type": "number"},
            {"name": "当时适配度", "field": "fit_rating", "type": "number"},
            {"name": "计划周期", "field": "plan_period", "type": "single_select", "enum": "plan_period"},
            {"name": "最爱", "field": "favorite", "type": "checkbox"},
            {"name": "优先级", "field": "priority", "type": "number"},
            {"name": "年份", "field": "year", "type": "number"},
            {"name": "导演", "field": "director", "type": "text"},
            {"name": "主演", "field": "actors", "type": "multi_select", "list": True},
            {"name": "国家地区", "field": "country_region", "type": "text"},
            {"name": "语言", "field": "language", "type": "text"},
            {"name": "时长分钟", "field": "duration_min", "type": "number"},
            {"name": "集数", "field": "episode_count", "type": "number"},
            {"name": "上映日期", "field": "release_date", "type": "date"},
            {"name": "简介", "field": "synopsis", "type": "text"},
            {"name": "推荐理由", "field": "recommend_reason", "type": "text"},
            {"name": "我的短评", "field": "user_comment", "type": "text"},
            {"name": "图片地址", "field": "poster_url", "type": "url"},
            {"name": "加入日期", "field": "added_date", "type": "date"},
            {"name": "看完日期", "field": "watched_date", "type": "date"},
            {"name": "已删除", "field": "deleted", "type": "checkbox"},
        ],
    },
    "history": {
        "name": "观影历史",
        "key_field": "item_id",
        "columns": [
            {"name": "本地编号", "field": "item_id", "type": "text"},
            {"name": "片名", "field": "title", "type": "text"},
            {"name": "看完日期", "field": "watched_date", "type": "date"},
            {"name": "我的评分", "field": "work_rating", "type": "number"},
            {"name": "当时适配度", "field": "fit_rating", "type": "number"},
            {"name": "短评", "field": "comment", "type": "text"},
            {"name": "反馈理由", "field": "feedback_reason", "type": "text"},
            {"name": "已删除", "field": "deleted", "type": "checkbox"},
        ],
    },
}


class FilmCuratorError(ValueError):
    pass


def _build_read_maps() -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """反向表：任何认识的写法（中文、英文、旧值）都译回内部英文标识符。"""
    names = {chinese: internal for internal, chinese in FIELD_NAMES.items()}
    for override in SUBTREE_FIELD_OVERRIDES.values():
        for internal, chinese in override.items():
            names[chinese] = internal
    names.update(FIELD_NAME_ALIASES)
    names.update({internal: internal for internal in FIELD_NAMES})
    values: dict[str, dict[str, str]] = {}
    for table, mapping in VALUE_NAMES.items():
        reverse = {chinese: internal for internal, chinese in mapping.items()}
        reverse.update({internal: internal for internal in mapping})
        reverse.update(VALUE_ALIASES.get(table, {}))
        values[table] = reverse
    return names, values


READ_FIELD_NAMES, READ_VALUE_NAMES = _build_read_maps()


def _convert_value(value: Any, table: str, direction: str) -> Any:
    if isinstance(value, list):
        return [_convert_value(item, table, direction) for item in value]
    if not isinstance(value, str) or not value:
        return value
    internal = READ_VALUE_NAMES[table].get(value, value)
    if direction == "decode":
        return internal
    return VALUE_NAMES[table].get(internal, internal)


def _convert(node: Any, direction: str, field_names: dict[str, str]) -> Any:
    """逐节点走一遍：只翻对照表里的键，其余原样透传。direction 是 encode 或 decode。"""
    if isinstance(node, list):
        return [_convert(child, direction, field_names) for child in node]
    if not isinstance(node, dict):
        return node
    result: dict[str, Any] = {}
    for key, child in node.items():
        internal = READ_FIELD_NAMES.get(key, key)
        result_key = field_names.get(internal, internal) if direction == "encode" else internal
        if internal in OPAQUE_KEYS:
            result[result_key] = copy.deepcopy(child)
            continue
        table = ENUM_FIELDS.get(internal)
        if table:
            result[result_key] = _convert_value(child, table, direction)
            continue
        child_names = field_names
        if internal in SUBTREE_FIELD_OVERRIDES:
            child_names = {**field_names, **SUBTREE_FIELD_OVERRIDES[internal]}
        result[result_key] = _convert(child, direction, child_names)
    return result


def decode_payload(payload: Any) -> Any:
    """文件内容 -> 内部结构。中文、英文、旧状态值都认。"""
    return _convert(payload, "decode", FIELD_NAMES)


def encode_payload(payload: Any, language: str = DEFAULT_FIELD_LANGUAGE) -> Any:
    """内部结构 -> 文件内容。language 为 en 时写英文键名。"""
    if language == "en":
        return decode_payload(payload)
    return _convert(payload, "encode", FIELD_NAMES)


FIELD_LANGUAGE_OVERRIDE: str | None = None
ACTIVE_DATA_DIR: Path = DEFAULT_DATA_DIR
_FIELD_LANGUAGE_CACHE: dict[str, str] = {}


def field_language(data_dir: Path) -> str:
    """写文件用哪种语言：命令行参数优先，其次 config.json，默认中文。"""
    if FIELD_LANGUAGE_OVERRIDE:
        return FIELD_LANGUAGE_OVERRIDE
    key = str(data_dir)
    if key in _FIELD_LANGUAGE_CACHE:
        return _FIELD_LANGUAGE_CACHE[key]
    language = DEFAULT_FIELD_LANGUAGE
    try:
        with (data_dir / "config.json").open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, json.JSONDecodeError):
        raw = None
    if isinstance(raw, dict):
        configured = decode_payload(raw).get("field_language")
        if configured in FIELD_LANGUAGES:
            language = configured
    _FIELD_LANGUAGE_CACHE[key] = language
    return language


def active_language() -> str:
    """本次执行用哪种语言。屏幕输出和报错跟数据文件保持一致。"""
    return field_language(ACTIVE_DATA_DIR)


def today_iso() -> str:
    return date.today().isoformat()


def read_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return decode_payload(json.load(handle))
    except FileNotFoundError as exc:
        raise FilmCuratorError(f"Missing data file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise FilmCuratorError(f"Invalid JSON in {path}: {exc}") from exc


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = encode_payload(value, field_language(path.parent))
    payload = json.dumps(encoded, ensure_ascii=False, indent=2) + "\n"
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def ensure_data(data_dir: Path) -> list[str]:
    data_dir.mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    for name, default in DEFAULT_FILES.items():
        path = data_dir / name
        if not path.exists():
            write_json(path, copy.deepcopy(default))
            created.append(name)
    return created


def _http_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    request = Request(
        f"{url}?{urlencode(params)}",
        headers={"Accept": "application/json", "User-Agent": "FilmCurator/1.0"},
    )
    with urlopen(request, timeout=METADATA_LOOKUP_TIMEOUT) as handle:
        return json.load(handle)


def _http_text(url: str, params: dict[str, Any], headers: dict[str, str] | None = None) -> str:
    request = Request(
        f"{url}?{urlencode(params)}",
        headers=headers or {"Accept": "text/html", "User-Agent": DOUBAN_USER_AGENT},
    )
    with urlopen(request, timeout=METADATA_LOOKUP_TIMEOUT) as handle:
        return handle.read().decode("utf-8", "replace")


# 常见繁简对应表，只处理影视元数据里反复出现的那批词，避免引入外部依赖。
_TRADITIONAL_TO_SIMPLIFIED: dict[str, str] = {
    "劇": "剧", "記": "记", "紀": "纪", "錄": "录", "錄影": "录影",
    "戰爭": "战争", "歷史": "历史", "歷": "历", "傳": "传", "導": "导",
    "演": "演", "員": "员", "動": "动", "畫": "画", "電": "电", "視": "视",
    "語": "语", "國": "国", "際": "际", "際": "际", "學": "学", "樂": "乐",
    "醫": "医", "警": "警", "懸": "悬", "疑": "疑", "驚": "惊", "悚": "悚",
    "愛": "爱", "情": "情", "喜": "喜", "歡": "欢", "獨": "独", "處": "处",
    "門": "门", "關": "关", "時": "时", "間": "间", "節": "节", "實": "实",
    "現": "现", "發": "发", "裏": "里", "裡": "里", "沒": "没", "這": "这",
    "個": "个", "為": "为", "與": "与", "於": "于", "後": "后", "們": "们",
    "來": "来", "對": "对", "說": "说", "給": "给", "會": "会", "長": "长",
    "場": "场", "將": "将", "應": "应", "當": "当", "無": "无", "點": "点",
    "員": "员", "演": "演", "懸疑": "悬疑", "科幻": "科幻", "動作": "动作",
    "冒險": "冒险", "奇幻": "奇幻", "恐怖": "恐怖", "驚悚": "惊悚",
    "家庭": "家庭", "犯罪": "犯罪", "戰爭": "战争", "音樂": "音乐",
    "歌舞": "歌舞", "武俠": "武侠", "古裝": "古装", "歷史": "历史",
    "戰爭片": "战争片", "劇情片": "剧情片", "喜劇": "喜剧", "愛情": "爱情",
    "紀錄片": "纪录片", "紀錄影片": "纪录片", "迷你影集": "迷你剧集",
    "影集": "剧集", "電視劇": "电视剧", "動畫": "动画", "動漫": "动漫",
    "搭檔": "搭档", "監獄": "监狱", "黑色": "黑色", "心理": "心理",
    "青春": "青春", "情節": "情节", "敘事": "叙事", "推理": "推理",
    "導演": "导演", "主演": "主演", "編劇": "编剧", "法蘭": "法兰",
    "紀錄": "纪录", "記錄": "记录", "紀錄影片": "纪录片", "紀錄片": "纪录片",
    "導演": "导演", "蘭": "兰",
    "達": "达", "維": "维", "納": "纳", "貝": "贝", "爾": "尔",
    "齊": "齐", "遜": "逊", "庫": "库", "布": "布", "裏": "里",
    "臺": "台", "灣": "湾", "廣": "广", "東": "东", "寧": "宁",
    "麗": "丽", "華": "华", "陽": "阳", "錦": "锦", "織": "织",
    "練": "练", "趙": "赵", "錢": "钱", "孫": "孙", "週": "周",
}


def simplify_chinese(value: Any) -> Any:
    """把繁体字转成简体，去重去空白；列表逐项处理，非文本原样返回。"""
    if isinstance(value, list):
        seen: list[str] = []
        for entry in value:
            simplified = simplify_chinese(entry)
            if isinstance(simplified, str) and simplified and simplified not in seen:
                seen.append(simplified)
        return seen
    if not isinstance(value, str):
        return value
    text = unicodedata.normalize("NFKC", value.strip())
    # 长的词先替换，避免「紀錄」把「紀錄影片」截断成「纪录影片」。
    for traditional, simplified in sorted(_TRADITIONAL_TO_SIMPLIFIED.items(), key=lambda pair: -len(pair[0])):
        text = text.replace(traditional, simplified)
    # 去掉 wikidata 风格的后缀括号注释，如「喜劇電影(日本)」→「喜劇電影」
    text = re.sub(r"\s*\([^)]*\)\s*$", "", text)
    return text.strip()


# 剧情简介里通常会出现的动作/情节词，用来区分「剧情简介」和「年份+类型的占位描述」。
_PLOT_HINTS = re.compile(
    r"(讲述|故事|饰|回到|踏上|寻找|决定|进入|面对|卷入|调查|爱上|组成|相遇|成为|"
    r"为了|试图|努力|经历|发现|收留|收养|重逢|离别|成长|冒险|追求|守护|揭露|真相|"
    r"案件|杀害|谋杀|死亡|发现|接受|爱上|离开|来到|开始|结束|放弃|拯救|逃避|隐瞒)"
)


def _is_placeholder_synopsis(text: str | None) -> bool:
    """判断简介是不是「占位式描述」而非影视剧情。

    历史数据来自维基数据时，会把片名匹配成同名概念实体（医学概念、人名、消歧义页、
    小说、漫画等），简介就成了「非正常死亡在法医学上指……」这种词条定义。
    这类占位简介应当被豆瓣的剧情简介覆盖，而不是因为「已有值」就保留。
    """
    t = simplify_chinese(text or "").strip()
    if not t:
        return False
    low = t.lower()
    if any(token in low for token in ("消歧义", "disambiguation", "男性人名", "女性人名", "系列漫画", "漫画系列")):
        return True
    # 纯「年份 + 类型」式描述，如「1993年美国电影」「2020年英国电视剧」。
    if re.fullmatch(r"\d{4}\s*年?[\w\s·\-—]*?(电影|电视剧|動畫|动画|动漫|纪录片|影片|剧集|剧|短片)", t):
        return True
    if re.fullmatch(r"\d{4} film by .+", low):
        return True
    # 词条定义句式。
    if any(mark in t for mark in ("是指", "又叫", "在法医学上", "是一种", "讀者会", "讀者會")):
        return True
    # 极短占位，如「电影」「电视剧」「日本电影」。
    if len(t) <= 6:
        return True
    # 较短且没有剧情动作词，多半是「年份/类型/导演/小说」式的元信息描述。
    if len(t) < 40 and not _PLOT_HINTS.search(t):
        return True
    return False



def _claim_values(entity: dict[str, Any], pid: str) -> list[Any]:
    values: list[Any] = []
    for claim in entity.get("claims", {}).get(pid, []):
        value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
        if value is not None:
            values.append(value)
    return values


def _entity_label(entity: dict[str, Any], preferred_language: str = "zh") -> str:
    labels = entity.get("labels", {}) if isinstance(entity, dict) else {}
    for language in (preferred_language, "zh", "en"):
        label = labels.get(language, {}).get("value")
        if label:
            return str(label)
    return ""


def _resolve_entity_labels(entity_ids: Iterable[str]) -> dict[str, str]:
    ids = [str(entity_id) for entity_id in entity_ids if str(entity_id).strip()]
    if not ids:
        return {}
    labels: dict[str, str] = {}
    for index in range(0, len(ids), 50):
        chunk = ids[index:index + 50]
        payload = _http_json(
            WIKIDATA_API_URL,
            {
                "action": "wbgetentities",
                "ids": "|".join(chunk),
                "languages": "zh|en",
                "languagefallback": 1,
                "props": "labels",
                "format": "json",
            },
        )
        for entity_id, entity in (payload.get("entities") or {}).items():
            if not isinstance(entity, dict):
                continue
            labels[entity_id] = _entity_label(entity)
    return labels


def _parse_wikidata_time(value: dict[str, Any]) -> str:
    time_value = str(value.get("time") or "")
    if len(time_value) >= 11:
        try:
            return datetime.strptime(time_value[1:11], "%Y-%m-%d").date().isoformat()
        except ValueError:
            return ""
    return ""


def _parse_quantity_minutes(value: dict[str, Any]) -> int | None:
    amount = value.get("amount")
    if amount is None:
        return None
    try:
        numeric = abs(float(amount))
    except (TypeError, ValueError):
        return None
    unit = str(value.get("unit") or "").lower()
    if "second" in unit or "q712226" in unit:
        return max(1, round(numeric / 60))
    if "hour" in unit:
        return max(1, round(numeric * 60))
    if "minute" in unit or "q7727" in unit:
        return max(1, round(numeric))
    if numeric > 240:
        return max(1, round(numeric / 60))
    return max(1, round(numeric))


def _content_type_from_labels(labels: Iterable[str]) -> str:
    joined = " ".join(str(label or "") for label in labels).lower()
    if any(term in joined for term in ("television series", "电视剧", "电视连续剧", "剧集")):
        return "series"
    if any(term in joined for term in ("documentary", "纪录片")):
        return "documentary"
    if any(term in joined for term in ("animated", "动画")):
        return "animation"
    if any(term in joined for term in ("short film", "short subject", "短片")):
        return "short"
    return "movie"


def _candidate_score_for_lookup(title: str, year: Any, result: dict[str, Any]) -> int:
    score = 0
    label = canonical_title(result.get("label"))
    if label and label == canonical_title(title):
        score += 6
    if year and str(year) in str(result.get("description") or ""):
        score += 2
    if str(result.get("description") or "").strip():
        score += 1
    return score


@lru_cache(maxsize=256)
def lookup_online_metadata(title: str, year: Any = None) -> dict[str, Any]:
    title = str(title or "").strip()
    if not title:
        return {}
    search_queries = [title]
    if year:
        search_queries.insert(0, f"{title} {year}")
    chosen_id = ""
    chosen_result: dict[str, Any] = {}
    for language in ("zh", "en"):
        for query in search_queries:
            try:
                payload = _http_json(
                    WIKIDATA_API_URL,
                    {
                        "action": "wbsearchentities",
                        "search": query,
                        "language": language,
                        "limit": 5,
                        "format": "json",
                        "uselang": language,
                    },
                )
            except (OSError, URLError, HTTPError, TimeoutError, ValueError):
                continue
            results = payload.get("search", []) if isinstance(payload, dict) else []
            if not results:
                continue
            best = max(results, key=lambda result: _candidate_score_for_lookup(title, year, result))
            entity_id = str(best.get("id") or "")
            if entity_id:
                chosen_id = entity_id
                chosen_result = best
                break
        if chosen_id:
            break
    if not chosen_id:
        return {}
    try:
        entity_payload = _http_json(
            WIKIDATA_API_URL,
            {
                "action": "wbgetentities",
                "ids": chosen_id,
                "languages": "zh|en",
                "languagefallback": 1,
                "props": "labels|descriptions|claims|sitelinks",
                "format": "json",
            },
        )
    except (OSError, URLError, HTTPError, TimeoutError, ValueError):
        return {}
    entity = (entity_payload.get("entities") or {}).get(chosen_id)
    if not isinstance(entity, dict):
        return {}

    metadata: dict[str, Any] = {}
    label_zh = _entity_label(entity, "zh")
    label_en = _entity_label(entity, "en")
    if label_en and canonical_title(label_en) != canonical_title(title):
        metadata["title_en"] = label_en

    description = ""
    for language in ("zh", "en"):
        description = str(entity.get("descriptions", {}).get(language, {}).get("value") or "").strip()
        if description:
            break

    summary = ""
    sitelinks = entity.get("sitelinks", {}) if isinstance(entity, dict) else {}
    for lang in ("zh", "en"):
        page = sitelinks.get(f"{lang}wiki", {}).get("title")
        if not page:
            continue
        try:
            summary_payload = _http_json(WIKIPEDIA_SUMMARY_URL.format(lang=lang, title=quote(str(page), safe="")), {})
        except (OSError, URLError, HTTPError, TimeoutError, ValueError):
            continue
        summary = str(summary_payload.get("extract") or "").strip()
        if summary:
            thumbnail = summary_payload.get("thumbnail", {}) if isinstance(summary_payload, dict) else {}
            if not metadata.get("poster_url") and isinstance(thumbnail, dict):
                metadata["poster_url"] = str(thumbnail.get("source") or "").strip()
            break

    if summary:
        metadata["synopsis"] = summary
    elif description:
        metadata["synopsis"] = description

    entity_label_ids = []
    for pid in ("P57", "P161", "P495", "P364", "P136", "P31"):
        for value in _claim_values(entity, pid):
            if isinstance(value, dict) and value.get("id"):
                entity_label_ids.append(str(value["id"]))
    try:
        label_map = _resolve_entity_labels(entity_label_ids)
    except (OSError, URLError, HTTPError, TimeoutError, ValueError):
        label_map = {}

    directors = [label_map.get(value["id"], "") for value in _claim_values(entity, "P57") if isinstance(value, dict) and value.get("id")]
    cast = [label_map.get(value["id"], "") for value in _claim_values(entity, "P161") if isinstance(value, dict) and value.get("id")]
    countries = [label_map.get(value["id"], "") for value in _claim_values(entity, "P495") if isinstance(value, dict) and value.get("id")]
    languages = [label_map.get(value["id"], "") for value in _claim_values(entity, "P364") if isinstance(value, dict) and value.get("id")]
    genres = [label_map.get(value["id"], "") for value in _claim_values(entity, "P136") if isinstance(value, dict) and value.get("id")]
    instance_labels = [label_map.get(value["id"], "") for value in _claim_values(entity, "P31") if isinstance(value, dict) and value.get("id")]

    publication_dates = [_parse_wikidata_time(value) for value in _claim_values(entity, "P577") if isinstance(value, dict)]
    release_date = next((value for value in publication_dates if value), "")
    if release_date:
        metadata.setdefault("release_date", release_date)
        metadata.setdefault("year", int(release_date[:4]))

    durations = [_parse_quantity_minutes(value) for value in _claim_values(entity, "P2047") if isinstance(value, dict)]
    duration_min = next((value for value in durations if value), None)
    if duration_min is not None:
        metadata.setdefault("duration_min", duration_min)

    if directors:
        metadata.setdefault("director", "、".join(dict.fromkeys([label for label in directors if label])))
    if cast:
        metadata.setdefault("actors", [label for label in dict.fromkeys(cast) if label][:8])
    if countries:
        metadata.setdefault("country_region", " / ".join(dict.fromkeys([label for label in countries if label])))
    if languages:
        metadata.setdefault("language", " / ".join(dict.fromkeys([label for label in languages if label])))
    if genres:
        metadata.setdefault("genres", [label for label in dict.fromkeys(genres) if label])
    inferred_type = _content_type_from_labels(instance_labels or [chosen_result.get("description", "") or label_zh or label_en])
    if inferred_type:
        metadata.setdefault("content_type", inferred_type)
    if not metadata.get("synopsis") and label_en:
        metadata["synopsis"] = chosen_result.get("description") or description or label_en
    return metadata


def _douban_search_result(title: str, subject_id: str = "", year: Any = None) -> dict[str, Any] | None:
    """从豆瓣搜索页抓匹配 subject_id 的结果块，返回评分/导演/主演/年份/简介等富信息。"""
    try:
        text = _http_text(DOUBAN_SEARCH_URL, {"cat": "1002", "q": title})
    except (OSError, URLError, HTTPError, TimeoutError, ValueError):
        return None
    blocks = re.split(r'<div class="result">', text)[1:]
    for block in blocks:
        sid = re.search(r'sid:\s*(\d+)', block)
        if subject_id and sid and sid.group(1) != subject_id:
            continue
        body = html.unescape(re.sub(r"<[^>]+>", " ", block))
        body = re.sub(r"\s+", " ", body).strip()
        if not body:
            continue
        rating = re.search(r'class="rating_nums">\s*([\d.]+)', block)
        cast = re.search(r'class="subject-cast">(.*?)</span>', block, re.S)
        kind = re.search(r"\[([^\]]+)\]", body)
        summary = re.search(r"<p>(.*?)</p>", block, re.S)
        result: dict[str, Any] = {}
        if sid:
            result["subject_id"] = sid.group(1)
        if rating:
            result["douban_rating"] = float(rating.group(1))
        if kind:
            label = kind.group(1).strip()
            if "电视" in label or "剧集" in label:
                result["content_type"] = "series"
            elif "纪录" in label:
                result["content_type"] = "documentary"
            elif "动画" in label:
                result["content_type"] = "animation"
            elif "短片" in label:
                result["content_type"] = "short"
        if cast:
            cast_text = html.unescape(re.sub(r"<[^>]+>", " ", cast.group(1)))
            parts = [part.strip() for part in re.split(r"\s*/\s*", cast_text) if part.strip()]
            if parts:
                original = parts[0]
                original = re.sub(r"^原名[:：]", "", original).strip()
                if original and canonical_title(original) != canonical_title(title):
                    result["title_en"] = simplify_chinese(original)
                # 末位是 4 位年份；第二位是导演；中间的都算主演。
                year_parts = [part for part in parts if re.fullmatch(r"\d{4}", part)]
                if year_parts:
                    result["year"] = int(year_parts[-1])
                names = [part for part in parts[1:] if not re.fullmatch(r"\d{4}", part)]
                if names:
                    result["director"] = simplify_chinese(names[0])
                if len(names) > 1:
                    result["actors"] = simplify_chinese(names[1:])[:8]
        if summary:
            result["synopsis"] = simplify_chinese(
                html.unescape(re.sub(r"<[^>]+>", "", summary.group(1)))
            )
        return result
    return None


def _douban_suggest(title: str) -> dict[str, Any] | None:
    """豆瓣联想接口，稳定返回中文片名、ID、年份、英文名、海报，作为搜索页的兜底。"""
    try:
        payload = _http_json(DOUBAN_SUGGEST_URL, {"q": title})
    except (OSError, URLError, HTTPError, TimeoutError, ValueError):
        return None
    results = payload if isinstance(payload, list) else []
    if not results:
        return None
    result: dict[str, Any] = {}
    for candidate in results:
        if not isinstance(candidate, dict):
            continue
        label = str(candidate.get("title") or "")
        if not label or canonical_title(label) != canonical_title(title):
            continue
        result["subject_id"] = str(candidate.get("id") or "")
        result["title_en"] = simplify_chinese(candidate.get("sub_title") or "")
        if str(candidate.get("year") or "").isdigit():
            result["year"] = int(str(candidate["year"]))
        poster = str(candidate.get("img") or "")
        if poster:
            result["poster_url"] = poster
        episode = str(candidate.get("episode") or "")
        if episode.isdigit():
            result["episode_count"] = int(episode)
        return result
    return None


def lookup_douban_metadata(title: str, year: Any = None) -> dict[str, Any]:
    """豆瓣数据源：联想接口锁定 ID，搜索页补评分/导演/主演/简介。"""
    suggest = _douban_suggest(title) or {}
    metadata = _douban_search_result(title, str(suggest.get("subject_id") or ""), year) or {}
    for field in ("subject_id", "title_en", "year", "poster_url", "episode_count"):
        if not metadata.get(field) and suggest.get(field):
            metadata[field] = suggest[field]
    for field in ("title_en", "director", "synopsis"):
        if metadata.get(field):
            metadata[field] = simplify_chinese(metadata[field])
    if "actors" in metadata:
        metadata["actors"] = simplify_chinese(metadata["actors"])
    return metadata



def enrich_record_metadata(record: dict[str, Any]) -> dict[str, Any]:
    item = copy.deepcopy(record or {})
    title = str(item.get("title") or "").strip()
    if not title:
        return item
    needs_lookup = any(
        not item.get(field)
        for field in ("synopsis", "genres", "content_type", "director", "duration_min", "language", "country_region", "release_date", "title_en", "douban_rating", "year", "poster_url")
    ) or _is_placeholder_synopsis(item.get("synopsis"))
    if not needs_lookup:
        return item
    metadata = lookup_douban_metadata(title, item.get("year"))
    if not metadata:
        return item
    for field, value in metadata.items():
        if field == "title_en":
            if not item.get("title_en"):
                item["title_en"] = value
            continue
        if field == "genres":
            if not item.get("genres"):
                item["genres"] = value
            continue
        if field == "actors":
            if not item.get("actors"):
                item["actors"] = value
            continue
        if field == "duration_min":
            if not item.get("duration_min"):
                item["duration_min"] = value
            continue
        if field == "year":
            if not item.get("year"):
                item["year"] = value
            continue
        if field == "douban_rating":
            if not item.get("douban_rating"):
                item["douban_rating"] = value
            continue
        if field == "release_date":
            if not item.get("release_date"):
                item["release_date"] = value
            continue
        if field == "poster_url":
            if not item.get("poster_url"):
                item["poster_url"] = value
            continue
        if field == "episode_count":
            if not item.get("episode_count"):
                item["episode_count"] = value
            continue
        if field == "content_type":
            if not item.get("content_type") or item.get("content_type") == "movie":
                item["content_type"] = value
            continue
        if field == "synopsis":
            # 简介只要空、或是占位式描述（词条定义/年份+类型），就用豆瓣剧情覆盖。
            if not item.get("synopsis") or _is_placeholder_synopsis(item.get("synopsis")):
                item["synopsis"] = value
            continue
        if field in {"director", "language", "country_region"}:
            if not item.get(field):
                item[field] = value
    return item


def _metadata_fields_missing(item: dict[str, Any]) -> list[str]:
    fields = ("synopsis", "genres", "content_type", "director", "duration_min", "language", "country_region", "release_date", "title_en", "douban_rating", "year", "poster_url")
    missing = [field for field in fields if not item.get(field)]
    if item.get("synopsis") and _is_placeholder_synopsis(item.get("synopsis")) and "synopsis" not in missing:
        missing.append("synopsis")
    return missing


def auto_enrich_missing_metadata(data_dir: Path) -> dict[str, Any]:
    """Retry metadata lookup for items that still have obvious missing facts."""
    ensure_data(data_dir)
    sources = {
        "watchlist": data_dir / "watchlist.json",
        "candidatePool": data_dir / "candidate_pool.json",
    }
    updated_files: set[str] = set()
    checked = updated = normalized = 0
    for file_name, path in sources.items():
        payload = read_json(path)
        items = payload.get("items", []) if isinstance(payload, dict) else []
        changed = False
        for index, item in enumerate(items):
            if not isinstance(item, dict) or not str(item.get("title") or "").strip():
                continue
            # 先统一已有文本的繁简/中英混杂，再做缺字段补全。
            for field in ("title_en", "director", "synopsis"):
                if item.get(field) and item.get(field) != simplify_chinese(item.get(field)):
                    item[field] = simplify_chinese(item[field])
                    changed = True
                    normalized += 1
            for field in ("genres", "actors"):
                if item.get(field) and item.get(field) != simplify_chinese(item.get(field)):
                    item[field] = simplify_chinese(item.get(field))
                    changed = True
                    normalized += 1
            missing = _metadata_fields_missing(item)
            if not missing:
                continue
            checked += 1
            enriched = enrich_record_metadata(item)
            # 豆瓣对高频请求会限流，节流一下避免批量补全时后半段大面积失败。
            time.sleep(0.5)
            if enriched != item:
                items[index] = enriched
                changed = True
                updated += 1
        if changed and isinstance(payload, dict):
            payload["items"] = items
            write_json(path, payload)
            updated_files.add(file_name)
    return {"checked": checked, "updated": updated, "normalized": normalized, "updated_files": sorted(updated_files)}


def split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def parse_scalar(value: str) -> Any:
    stripped = value.strip()
    if stripped in {"true", "false", "null"}:
        return json.loads(stripped)
    if stripped.startswith(("[", "{", '"')):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass
    try:
        return int(stripped)
    except ValueError:
        try:
            return float(stripped)
        except ValueError:
            return value


# 记录本身能有的字段。写错名字会被拒绝，不会默默新建一个没人读的字段。
ITEM_WRITABLE_FIELDS: frozenset[str] = frozenset({
    "id", "title", "title_en", "year", "director", "actors", "country_region",
    "language", "genres", "tags", "moods", "content_type", "duration_min",
    "episode_count", "watch_episodes", "watch_duration_min", "release_date",
    "douban_rating", "work_rating", "fit_rating", "status", "favorite",
    "plan_period", "priority", "synopsis", "recommend_reason", "user_comment",
    "poster_url", "source", "source_tier", "candidate_id", "added_date",
    "watched_date", "strategy_tag", "feedback_reason", "is_example",
})

# 这几个字段在文件里是列表。用 --set 传「剧情,动作」这种写法时自动拆开，
# 否则会存成一整串文字，跟其他记录格式不一致，筛选和统计都会漏掉它。
ITEM_LIST_FIELDS: frozenset[str] = frozenset({"genres", "tags", "moods", "actors"})


def parse_assignments(values: Iterable[str], allowed: frozenset[str] | None = None) -> dict[str, Any]:
    """--set 支持中文字段名和中文取值：状态=已看 与 status=watched 等价。

    传了 allowed 就校验字段名，写错直接报错并给出可用的写法，
    避免拼错字段名后数据被静默写进一个无效键。
    """
    updates: dict[str, Any] = {}
    for assignment in values:
        if "=" not in assignment:
            raise FilmCuratorError(f"Expected FIELD=VALUE, got {assignment!r}")
        field, raw = assignment.split("=", 1)
        field = field.strip()
        if not field:
            raise FilmCuratorError("Field name cannot be empty")
        internal = READ_FIELD_NAMES.get(field, field)
        if allowed is not None and internal not in allowed:
            known = sorted(FIELD_NAMES[name] for name in allowed if name in FIELD_NAMES)
            raise FilmCuratorError(
                f"Unknown field: {field}. 可用字段：{'、'.join(known)}"
            )
        table = ENUM_FIELDS.get(internal)
        value = parse_scalar(raw)
        if table:
            updates[internal] = _convert_value(value, table, "decode")
        elif internal in ITEM_LIST_FIELDS and isinstance(value, str):
            parts = (piece.strip() for piece in re.split(r"[,，、;；|]", value))
            updates[internal] = [piece for piece in parts if piece]
        else:
            updates[internal] = value
    return updates


def normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    """Migrate legacy records into the unified record schema."""
    normalized = copy.deepcopy(item)
    normalized.pop("zone", None)
    normalized.pop("watch_cue", None)
    if normalized.get("status") in {"planned", "paused"}:
        normalized["status"] = "want"
    normalized.setdefault("content_type", "movie")
    normalized.setdefault("actors", [])
    normalized.setdefault("country_region", "")
    normalized.setdefault("language", "")
    normalized.setdefault("episode_count", None)
    normalized.setdefault("watch_episodes", None)
    normalized.setdefault("watch_duration_min", None)
    normalized.setdefault("release_date", "")
    normalized.setdefault("status", "want")
    normalized.setdefault("favorite", False)
    normalized.setdefault("douban_rating", None)
    normalized.setdefault("work_rating", None)
    normalized.setdefault("fit_rating", None)
    normalized.setdefault("plan_period", "")
    normalized.setdefault("added_date", today_iso())
    return normalized


def field_label(name: str) -> str:
    """报错里用读者能在文件里看到的那个字段名。"""
    if active_language() == "en":
        return name
    return FIELD_NAMES.get(name, name)


def value_label(field: str, value: Any) -> Any:
    table = ENUM_FIELDS.get(field)
    if not table or active_language() == "en":
        return value
    return _convert_value(value, table, "encode")


def validate_item(item: dict[str, Any]) -> None:
    required = ("id", "title", "content_type", "status", "added_date")
    missing = [field_label(field) for field in required if not item.get(field)]
    if missing:
        raise FilmCuratorError(f"Missing required item fields: {', '.join(missing)}")
    if item["content_type"] not in CONTENT_TYPES:
        raise FilmCuratorError(f"Unsupported {field_label('content_type')}: {value_label('content_type', item['content_type'])}")
    if item["status"] not in ALL_STATUSES:
        raise FilmCuratorError(f"Unsupported {field_label('status')}: {value_label('status', item['status'])}")
    for field in ("work_rating", "fit_rating", "douban_rating"):
        rating = item.get(field)
        if rating is not None and not 0 <= float(rating) <= 10:
            raise FilmCuratorError(f"{field_label(field)} must be between 0 and 10")


def find_item(items: list[dict[str, Any]], item_id: str) -> dict[str, Any]:
    for item in items:
        if item.get("id") == item_id:
            return item
    raise FilmCuratorError(f"Unknown item id: {item_id}")


# 摘要里只留定位和确认版本需要的字段。目的是让调用方不必为了拿一个 id 去读整份片单，
# 那样既慢又容易在临时写的解析代码里出错。
FIND_SUMMARY_FIELDS = (
    "id", "title", "title_en", "year", "director", "content_type",
    "status", "work_rating", "fit_rating", "plan_period", "watched_date",
)


def find_items_by_title(data_dir: Path, query: str, exact: bool = False) -> dict[str, Any]:
    """按片名查记录，用与判重同一套规范化规则（canonical_title）。

    exact=True 只认规范化后完全相等的；默认再补一档包含匹配，
    并把两类分开返回，避免调用方把「特洛伊战争纪实」当成「特洛伊」改掉。
    """
    ensure_data(data_dir)
    text = str(query or "").strip()
    if not text:
        raise FilmCuratorError("search title cannot be empty")
    target = canonical_title(text)
    items = read_json(data_dir / "watchlist.json").get("items", [])
    candidates = read_json(data_dir / "candidate_pool.json").get("items", [])

    def summarize(item: dict[str, Any], where: str) -> dict[str, Any]:
        summary = {field: item.get(field) for field in FIND_SUMMARY_FIELDS if field in item}
        summary["found_in"] = where
        if item.get("is_example"):
            summary["is_example"] = True
        return summary

    exact_hits: list[dict[str, Any]] = []
    partial_hits: list[dict[str, Any]] = []
    for pool, where in ((items, "watchlist"), (candidates, "candidate_pool")):
        for item in pool:
            if not isinstance(item, dict):
                continue
            name = canonical_title(item.get("title"))
            if not name:
                continue
            if name == target:
                exact_hits.append(summarize(item, where))
            elif not exact and target in name:
                partial_hits.append(summarize(item, where))
    return {
        "query": text,
        "exact_matches": exact_hits,
        "partial_matches": [] if exact else partial_hits,
        "exact_count": len(exact_hits),
        "partial_count": 0 if exact else len(partial_hits),
    }


def add_item(data_dir: Path, values: dict[str, Any]) -> dict[str, Any]:
    ensure_data(data_dir)
    watchlist_path = data_dir / "watchlist.json"
    watchlist = read_json(watchlist_path)
    item = {
        "id": values.get("id") or str(uuid.uuid4()),
        "title": values["title"].strip(),
        "title_en": values.get("title_en") or "",
        "year": values.get("year"),
        "director": values.get("director") or "",
        "actors": values.get("actors") or [],
        "country_region": values.get("country_region") or "",
        "language": values.get("language") or "",
        "genres": values.get("genres") or [],
        "content_type": values.get("content_type") or "movie",
        "duration_min": values.get("duration_min"),
        "episode_count": values.get("episode_count"),
        "watch_episodes": values.get("watch_episodes"),
        "watch_duration_min": values.get("watch_duration_min"),
        "release_date": values.get("release_date") or "",
        "synopsis": values.get("synopsis") or "",
        "poster_url": values.get("poster_url") or "",
        "source": values.get("source") or "manual",
        "recommend_reason": values.get("recommend_reason") or "",
        "strategy_tag": values.get("strategy_tag") or "",
        "status": values.get("status") or "want",
        "favorite": bool(values.get("favorite", False)),
        "douban_rating": values.get("douban_rating"),
        "work_rating": values.get("work_rating"),
        "fit_rating": values.get("fit_rating"),
        "user_comment": values.get("user_comment") or "",
        "tags": values.get("tags") or [],
        "moods": values.get("moods") or [],
        "plan_period": values.get("plan_period") or "",
        "priority": int(values.get("priority") or 0),
        "added_date": values.get("added_date") or today_iso(),
        "watched_date": values.get("watched_date"),
    }
    if values.get("is_example"):
        item["is_example"] = True
    if not item["title"]:
        raise FilmCuratorError("title cannot be empty")
    if any(existing.get("id") == item["id"] for existing in watchlist["items"]):
        raise FilmCuratorError(f"Duplicate item id: {item['id']}")
    validate_item(item)
    watchlist["items"].append(item)
    write_json(watchlist_path, watchlist)
    return item


def update_item(data_dir: Path, item_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    ensure_data(data_dir)
    path = data_dir / "watchlist.json"
    watchlist = read_json(path)
    item = find_item(watchlist["items"], item_id)
    item.update(updates)
    item = normalize_item(item)
    watchlist["items"] = [item if entry.get("id") == item_id else entry for entry in watchlist["items"]]
    validate_item(item)
    write_json(path, watchlist)
    return item


def remove_item(data_dir: Path, item_id: str) -> dict[str, Any]:
    ensure_data(data_dir)
    path = data_dir / "watchlist.json"
    watchlist = read_json(path)
    item = find_item(watchlist["items"], item_id)
    watchlist["items"] = [entry for entry in watchlist["items"] if entry.get("id") != item_id]
    write_json(path, watchlist)
    return item


def learn_from_rating(profile: dict[str, Any], item: dict[str, Any], rating: float) -> None:
    """单条已看记录的评分学习：只累加，不封顶。由 refresh 逐条调用后统一排序。"""
    profile.setdefault("genre_weights", {})
    # 评分越高的片贡献越大；低于 6 分是负信号，把相关标签往下拉。
    if rating >= 9:
        delta = 1.0
    elif rating >= 8:
        delta = 0.8
    elif rating >= 7:
        delta = 0.5
    elif rating >= 6:
        delta = 0.2
    else:
        delta = -0.5
    # 用户自己的标签最能反映喜好；没有标签时才退回客观类型（genres），两者不混用。
    source = item.get("tags") or item.get("genres") or []
    signal_labels: list[str] = []
    for label in source:
        label = simplify_chinese(label)
        if label and label not in signal_labels:
            signal_labels.append(label)
    for genre in signal_labels:
        profile["genre_weights"][genre] = round(float(profile["genre_weights"].get(genre, 0)) + delta, 3)
    profile["ratings_count"] = int(profile.get("ratings_count", 0)) + 1
    if rating >= 8:
        profile["high_ratings_count"] = int(profile.get("high_ratings_count", 0)) + 1
    profile["last_updated"] = today_iso()


def refresh_profile_from_watchlist(data_dir: Path) -> dict[str, Any]:
    """按当前影单里的全部已看记录重算画像，保证画像和记录库实时一致。

    幂等：先清空由评分推导出来的字段，再逐条重放，重复调用不会翻倍计数。
    权重 = 评分贡献（高分更多）× 出现次数（log 平滑），高频标签不再和低频标签并列封顶。
    """
    ensure_data(data_dir)
    profile_path = data_dir / "user_profile.json"
    profile = read_json(profile_path)
    profile["genre_weights"] = {}
    profile["ratings_count"] = 0
    profile["high_ratings_count"] = 0
    profile["last_updated"] = today_iso()
    items = read_json(data_dir / "watchlist.json").get("items", [])
    counted = 0
    for item in items:
        if not isinstance(item, dict) or item.get("is_example"):
            continue
        if item.get("status") != "watched":
            continue
        rating = item.get("work_rating")
        if rating is None:
            continue
        learn_from_rating(profile, item, float(rating))
        counted += 1
    # 出现次数用于平滑：两次比一次更有分量，但不会无上限线性涨。
    weights = profile.get("genre_weights", {})
    frequency: Counter = Counter()
    for item in items:
        if not isinstance(item, dict) or item.get("is_example"):
            continue
        if item.get("status") != "watched":
            continue
        for label in (item.get("tags") or item.get("genres") or []):
            label = simplify_chinese(label)
            if label:
                frequency[label] += 1
    for genre, raw in weights.items():
        count = frequency.get(genre, 1)
        profile["genre_weights"][genre] = round(raw * (1.0 + math.log(count)), 3)
    ranked = sorted(
        profile["genre_weights"].items(),
        key=lambda pair: (-pair[1], -frequency.get(pair[0], 0), pair[0]),
    )
    profile["preferred_genres"] = [genre for genre, weight in ranked if weight > 0][:8]
    if counted:
        profile.pop("is_example", None)
    write_json(profile_path, profile)
    return {
        "counted": counted,
        "preferred_genres": profile["preferred_genres"],
        "high_ratings_count": profile["high_ratings_count"],
    }



def record_preference_evidence(
    data_dir: Path,
    signal: str,
    source: str,
    reason: str = "",
    related_item: str = "",
    confirmed: bool = False,
    evidence_date: str | None = None,
) -> dict[str, Any]:
    """Store an auditable preference observation without forcing a profile conclusion."""
    ensure_data(data_dir)
    if not signal.strip():
        raise FilmCuratorError("preference signal is required")
    event = {
        "id": str(uuid.uuid4()),
        "signal": signal.strip(),
        "source": source.strip() or "conversation",
        "reason": reason.strip(),
        "related_item": related_item.strip(),
        "confirmed": bool(confirmed),
        "date": evidence_date or today_iso(),
    }
    path = data_dir / "preference_evidence.json"
    evidence = read_json(path)
    evidence.setdefault("events", []).append(event)
    write_json(path, evidence)
    return event


def feedback_prompt_candidates(data_dir: Path) -> list[dict[str, Any]]:
    """Return completed items that have not yet received a follow-up prompt."""
    ensure_data(data_dir)
    profile = read_json(data_dir / "user_profile.json")
    prompted = {str(item_id) for item_id in profile.get("feedback_prompted_item_ids", [])}
    history = read_json(data_dir / "history.json").get("events", [])
    items = {str(item.get("id")): item for item in read_json(data_dir / "watchlist.json").get("items", [])}
    pending = []
    for event in history:
        item_id = str(event.get("item_id") or "")
        if not item_id or item_id in prompted or event.get("is_example"):
            continue
        item = items.get(item_id)
        if item and item.get("status") == "watched":
            pending.append({"item_id": item_id, "title": item.get("title", event.get("title", "")), "watched_date": event.get("watched_date")})
    return pending


def mark_feedback_prompted(data_dir: Path, item_id: str) -> list[str]:
    ensure_data(data_dir)
    profile_path = data_dir / "user_profile.json"
    profile = read_json(profile_path)
    prompted = [str(value) for value in profile.get("feedback_prompted_item_ids", [])]
    if item_id not in prompted:
        prompted.append(item_id)
    profile["feedback_prompted_item_ids"] = prompted
    profile["last_updated"] = today_iso()
    write_json(profile_path, profile)
    return prompted


def complete_item(
    data_dir: Path,
    item_id: str,
    rating: float | None,
    comment: str,
    watched_date: str,
    work_rating: float | None = None,
    fit_rating: float | None = None,
    feedback_reason: str = "",
    session_id: str = "",
) -> dict[str, Any]:
    # --rating 和 --work-rating 是同一个分数的两种写法（前者是旧参数名），合并成 work_rating。
    if rating is not None and not 0 <= rating <= 10:
        raise FilmCuratorError("rating must be between 0 and 10")
    for name, value in (("work_rating", work_rating), ("fit_rating", fit_rating)):
        if value is not None and not 0 <= value <= 10:
            raise FilmCuratorError(f"{name} must be between 0 and 10")
    if work_rating is None and rating is not None:
        work_rating = rating
    item = update_item(
        data_dir,
        item_id,
        {
            "status": "watched",
            "watched_date": watched_date,
            "user_comment": comment,
            "work_rating": work_rating,
            "fit_rating": fit_rating,
            "feedback_reason": feedback_reason,
        },
    )
    item.pop("is_example", None)
    watchlist_path = data_dir / "watchlist.json"
    watchlist = read_json(watchlist_path)
    find_item(watchlist["items"], item_id).pop("is_example", None)
    write_json(watchlist_path, watchlist)
    history_path = data_dir / "history.json"
    history = read_json(history_path)
    history["events"] = [event for event in history["events"] if event.get("item_id") != item_id]
    history["events"].append(
        {
            "item_id": item_id,
            "title": item["title"],
            "watched_date": watched_date,
            "work_rating": work_rating,
            "fit_rating": fit_rating,
            "comment": comment,
            "feedback_reason": feedback_reason,
            "session_id": session_id,
        }
    )
    write_json(history_path, history)

    if work_rating is not None:
        refresh_profile_from_watchlist(data_dir)

    log_path = data_dir / "recommend_log.json"
    log = read_json(log_path)
    log["events"].append(
        {
            "item_id": item_id,
            "title": item["title"],
            "strategy": item.get("strategy_tag") or "manual",
            "feedback": "watched",
            "event_type": "completed",
            "date": watched_date,
            "session_id": session_id,
            "fit_rating": fit_rating,
            "work_rating": work_rating,
            "feedback_reason": feedback_reason,
        }
    )
    write_json(log_path, log)
    return item


def update_profile(data_dir: Path, updates: dict[str, Any]) -> dict[str, Any]:
    ensure_data(data_dir)
    path = data_dir / "user_profile.json"
    profile = read_json(path)
    profile.update(updates)
    profile.pop("profile_confidence", None)
    profile["last_updated"] = today_iso()
    write_json(path, profile)
    return profile


def log_recommendation(
    data_dir: Path,
    title: str,
    strategy: str,
    event_type: str,
    item_id: str = "",
    context: str = "",
    event_date: str | None = None,
    session_id: str = "",
    source_tier: str = "",
    feedback_reason: str = "",
) -> dict[str, Any]:
    ensure_data(data_dir)
    if not title.strip():
        raise FilmCuratorError("recommendation title is required")
    if event_type not in {"exposed", "accepted", "skipped", "started", "completed", "dropped"}:
        raise FilmCuratorError("recommendation event must be exposed, accepted, skipped, started, completed, or dropped")
    event: dict[str, Any] = {
        "title": title.strip(),
        "strategy": strategy or "precise_match",
        "event_type": event_type,
        "date": event_date or today_iso(),
    }
    if item_id:
        event["item_id"] = item_id
    if context:
        event["context"] = context
    if session_id:
        event["session_id"] = session_id
    if source_tier:
        event["source_tier"] = source_tier
    if feedback_reason:
        event["feedback_reason"] = feedback_reason
    if event_type in {"accepted", "skipped", "started", "completed", "dropped"}:
        event["feedback"] = event_type
    path = data_dir / "recommend_log.json"
    log = read_json(path)
    log.setdefault("events", []).append(event)
    write_json(path, log)
    return event


def create_recommendation_session(data_dir: Path, context: str = "", scope: str = "dynamic") -> dict[str, Any]:
    ensure_data(data_dir)
    if scope not in {"dynamic", "library", "external", "theme", "rewatch"}:
        raise FilmCuratorError("unsupported recommendation scope")
    event = {
        "session_id": f"rec-{date.today().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}",
        "event_type": "session_started",
        "scope": scope,
        "context": context,
        "date": today_iso(),
    }
    path = data_dir / "recommend_log.json"
    log = read_json(path)
    log.setdefault("events", []).append(event)
    write_json(path, log)
    return event


def recent_titles(data_dir: Path, days: int = 14) -> set[str]:
    cutoff = date.today() - timedelta(days=days)
    titles: set[str] = set()
    history = read_json(data_dir / "history.json")
    log = read_json(data_dir / "recommend_log.json")
    for event in [*history.get("events", []), *log.get("events", [])]:
        if event.get("is_example"):
            continue
        raw_date = event.get("watched_date") or event.get("date")
        try:
            event_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            continue
        if event_date >= cutoff and event.get("title"):
            titles.add(event["title"].casefold())
    return titles


def score_candidate(
    candidate: dict[str, Any],
    profile: dict[str, Any],
    recent: set[str],
    mood: str,
    duration: int | None,
    language_mode: str = "normal",
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    genres = set(candidate.get("genres") or [])
    preferred = set(profile.get("preferred_genres") or [])
    avoided = set(profile.get("avoided_genres") or [])
    matches = genres & preferred
    conflicts = genres & avoided
    if matches:
        score += 3 * len(matches)
        reasons.append("matches preferred genres: " + ", ".join(sorted(matches)))
    if conflicts:
        score -= 8 * len(conflicts)
        reasons.append("contains avoided genres: " + ", ".join(sorted(conflicts)))
    for genre in genres:
        score += float(profile.get("genre_weights", {}).get(genre, 0))
    if candidate.get("director") in set(profile.get("favorite_directors") or []):
        score += 3
        reasons.append("favorite director")
    actors = set(candidate.get("actors") or [])
    if actors & set(profile.get("favorite_actors") or []):
        score += 2
        reasons.append("favorite cast")
    candidate_language_values = {
        token.strip() for token in str(candidate.get("language") or "").replace("/", "、").replace(";", "、").replace("|", "、").replace(",", "、").split("、")
        if token.strip()
    }
    preferred_languages = {str(language).strip() for language in (profile.get("preferred_languages") or []) if str(language).strip()}
    avoided_languages = {str(language).strip() for language in (profile.get("avoided_languages") or []) if str(language).strip()}
    if candidate_language_values & preferred_languages:
        score += 2
        reasons.append("fits preferred language")
    if candidate_language_values & avoided_languages:
        score -= 3
        reasons.append("avoids preferred language conflict")
    if language_mode == "subtitle_sensitive" and candidate_language_values:
        if preferred_languages:
            if not (candidate_language_values & preferred_languages):
                score -= 1
                reasons.append("subtitle-light context favors easier language")
        else:
            simplified = {"中文", "国语", "普通话", "粤语", "汉语", "华语"}
            if not (candidate_language_values & simplified):
                score -= 1
                reasons.append("subtitle-light context favors easier language")
    mood_terms = set(candidate.get("moods") or []) | set(candidate.get("tags") or [])
    if mood and mood in mood_terms:
        score += 1
        reasons.append("fits requested mood")
    if duration and candidate.get("duration_min") and int(candidate["duration_min"]) <= duration:
        score += 1
        reasons.append("fits available time")
    # 时长未知不再排除，改为降权：项目本身允许时长查不到就留空，硬排除会把
    # 大量只有片名的记录全部挡在推荐之外。降权后它们排在有确切时长的后面，
    # 但仍然可选，理由里标出未知让用户自己判断。
    if duration and not (candidate.get("watch_duration_min") or candidate.get("duration_min")):
        score -= 0.5
        reasons.append("duration unknown, may not fit available time")
    if str(candidate.get("title", "")).casefold() in recent:
        score -= 4
        reasons.append("recently surfaced")
    return round(score, 2), reasons


def candidate_filter_reason(
    candidate: dict[str, Any], avoided: set[str], recent: set[str], unavailable_titles: set[str], duration: int | None
) -> str:
    if not candidate.get("title"):
        return "missing_title"
    if set(candidate.get("genres") or []) & avoided:
        return "avoided_genre"
    if str(candidate.get("title", "")).casefold() in recent:
        return "recently_surfaced"
    if canonical_title(candidate.get("title")) in unavailable_titles:
        return "already_watched_or_dropped"
    if duration is not None:
        candidate_duration = candidate.get("watch_duration_min") or candidate.get("duration_min")
        # 时长未知的不排除。项目允许时长查不到就留空，硬排除会让「只有片名的
        # 影单」在带时长约束时全军覆没。这类记录交给 score_candidate 降权，
        # 排在有确切时长的后面。只有确切超时的才真排除。
        if candidate_duration is not None and int(candidate_duration) > duration:
            return "too_long"
    return ""


def diverse_selection(ranked: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    selected = ranked[:limit]
    available_types = {item.get("content_type") for item in ranked}
    selected_types = {item.get("content_type") for item in selected}
    if limit >= 2 and len(available_types) >= 2 and len(selected_types) < 2:
        replacement = next(
            (item for item in ranked[limit:] if item.get("content_type") not in selected_types), None
        )
        if replacement:
            selected[-1] = replacement
    return selected


def rank_candidates(
    data_dir: Path,
    candidates: list[dict[str, Any]],
    limit: int,
    mood: str,
    duration: int | None,
    language_mode: str = "normal",
) -> list[dict[str, Any]]:
    ensure_data(data_dir)
    profile = read_json(data_dir / "user_profile.json")
    recent = recent_titles(data_dir)
    avoided = set(profile.get("avoided_genres") or [])
    unavailable_titles = {
        canonical_title(item.get("title"))
        for item in read_json(data_dir / "watchlist.json").get("items", [])
        if not item.get("is_example") and item.get("status") in {"watched", "dropped"}
    }
    ranked: list[dict[str, Any]] = []
    for candidate in candidates:
        if candidate_filter_reason(candidate, avoided, recent, unavailable_titles, duration):
            continue
        item = copy.deepcopy(candidate)
        item.setdefault("content_type", "movie")
        item.setdefault("source_tier", "external")
        item["score"], item["score_reasons"] = score_candidate(item, profile, recent, mood, duration, language_mode)
        item.setdefault("strategy_tag", "precise_match")
        ranked.append(item)
    ranked.sort(key=lambda item: (-item["score"], item["title"].casefold()))
    return diverse_selection(ranked, max(1, limit))


def recommendation_diagnostics(
    data_dir: Path,
    candidates: list[dict[str, Any]],
    limit: int,
    mood: str,
    duration: int | None,
    language_mode: str = "normal",
) -> dict[str, Any]:
    ensure_data(data_dir)
    profile = read_json(data_dir / "user_profile.json")
    recent = recent_titles(data_dir)
    unavailable = {
        canonical_title(item.get("title"))
        for item in read_json(data_dir / "watchlist.json").get("items", [])
        if not item.get("is_example") and item.get("status") in {"watched", "dropped"}
    }
    avoided = set(profile.get("avoided_genres") or [])
    excluded = []
    eligible = []
    for candidate in candidates:
        reason = candidate_filter_reason(candidate, avoided, recent, unavailable, duration)
        if reason:
            excluded.append({"title": candidate.get("title", ""), "reason": reason})
        else:
            eligible.append(candidate)
    return {"selected": rank_candidates(data_dir, eligible, limit, mood, duration, language_mode), "excluded": excluded}


def adopt_candidate(data_dir: Path, candidate: dict[str, Any], plan_period: str = "") -> dict[str, Any]:
    ensure_data(data_dir)
    if not candidate.get("title"):
        raise FilmCuratorError("candidate title is required")
    existing = read_json(data_dir / "watchlist.json").get("items", [])
    duplicate = next((item for item in existing if canonical_title(item.get("title")) == canonical_title(candidate.get("title"))), None)
    if duplicate:
        raise FilmCuratorError(f"Candidate already exists as item id: {duplicate.get('id')}")
    values = enrich_record_metadata(copy.deepcopy(candidate))
    values.update({"status": "want", "plan_period": plan_period, "source": candidate.get("source") or "external", "strategy_tag": candidate.get("strategy_tag") or "precise_match"})
    return add_item(data_dir, values)


def build_recommendation_pool(
    data_dir: Path,
    external_candidates: list[dict[str, Any]],
    limit: int = 3,
    mood: str = "",
    duration: int | None = None,
    allow_external: bool = True,
    scope: str = "dynamic",
    language_mode: str = "normal",
) -> list[dict[str, Any]]:
    """Build a dynamic pool: use eligible library items first, then fill gaps externally.

    The library is treated as evidence, not truth. A user can explicitly request only the
    library; otherwise external candidates are admitted when the library cannot satisfy the
    requested number or when the user asks to explore.
    """
    ensure_data(data_dir)
    if scope not in {"dynamic", "library", "external"}:
        raise FilmCuratorError("recommendation scope must be dynamic, library, or external")
    watchlist = read_json(data_dir / "watchlist.json")
    library = [
        copy.deepcopy(item)
        for item in watchlist.get("items", [])
        if not item.get("is_example") and item.get("status") in {"want", "watching"}
    ]
    if scope == "library":
        return rank_candidates(data_dir, [{**item, "source_tier": "library"} for item in library], limit, mood, duration, language_mode)
    if scope == "external":
        return rank_candidates(data_dir, [{**item, "source_tier": "external"} for item in external_candidates], limit, mood, duration, language_mode)

    library_ranked = rank_candidates(data_dir, [{**item, "source_tier": "library"} for item in library], limit, mood, duration, language_mode)
    if not allow_external or len(library_ranked) >= limit:
        return library_ranked[:limit]
    library_titles = {canonical_title(item.get("title")) for item in library_ranked}
    external_ranked = rank_candidates(
        data_dir,
        [{**item, "source_tier": "external"} for item in external_candidates if canonical_title(item.get("title")) not in library_titles],
        limit - len(library_ranked),
        mood,
        duration,
        language_mode,
    )
    return library_ranked + external_ranked


def load_external_candidates(path: Path) -> list[dict[str, Any]]:
    """Load external candidates while preserving their provenance."""
    payload = read_json(path)
    if isinstance(payload, dict):
        candidates = payload.get("candidates", payload.get("items", []))
    else:
        candidates = payload
    if not isinstance(candidates, list):
        raise FilmCuratorError("external candidate file must contain a JSON array or candidates list")
    normalized: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict) or not str(candidate.get("title") or "").strip():
            continue
        item = copy.deepcopy(candidate)
        item["source_tier"] = "external"
        item.setdefault("source", "external")
        item.setdefault("candidate_id", f"external-{canonical_title(item['title'])}-{index + 1}")
        item = enrich_record_metadata(item)
        normalized.append(item)
    return normalized


def load_candidate_pool(data_dir: Path) -> list[dict[str, Any]]:
    ensure_data(data_dir)
    payload = read_json(data_dir / "candidate_pool.json")
    items = payload.get("items", []) if isinstance(payload, dict) else []
    return [copy.deepcopy(item) for item in items if isinstance(item, dict) and str(item.get("title") or "").strip()]


CANDIDATE_SUMMARY_FIELDS = (
    "title", "title_en", "year", "director", "content_type", "genres",
    "douban_rating", "duration_min", "source", "captured_at", "recommend_reason",
)


def survey_candidate_pool(
    data_dir: Path,
    query: str = "",
    limit: int = 0,
    stats_only: bool = False,
) -> dict[str, Any]:
    """查阅候选待看清单，不改数据。

    候选池是用户提供或检索到、尚未采纳为正式待看的备选清单。它可能有几百条，
    整份读进上下文很贵，所以这里默认只回统计 + 精简字段，按需再筛。
    query 按片名、导演、类型、标签做包含匹配；limit 限制返回条数（0 为不限）。
    """
    items = load_candidate_pool(data_dir)
    real = [item for item in items if not item.get("is_example")]

    content_types: Counter[str] = Counter()
    genres: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    with_duration = 0
    for item in real:
        if item.get("content_type"):
            content_types[item["content_type"]] += 1
        genres.update(item.get("genres") or [])
        if item.get("source"):
            sources[item["source"]] += 1
        if item.get("watch_duration_min") or item.get("duration_min"):
            with_duration += 1

    summary: dict[str, Any] = {
        "total": len(real),
        "content_types": dict(content_types),
        "top_genres": genres.most_common(10),
        "sources": dict(sources),
        "with_duration": with_duration,
        "without_duration": len(real) - with_duration,
    }
    if stats_only:
        return summary

    matched = real
    if query:
        needle = str(query).strip().casefold()
        target = canonical_title(query)

        def hit(item: dict[str, Any]) -> bool:
            if target and target in canonical_title(item.get("title")):
                return True
            haystack = [item.get("title_en"), item.get("director"), item.get("recommend_reason")]
            haystack.extend(item.get("genres") or [])
            haystack.extend(item.get("tags") or [])
            return any(needle in str(value).casefold() for value in haystack if value)

        matched = [item for item in real if hit(item)]

    summary["query"] = query
    summary["matched"] = len(matched)
    shown = matched[:limit] if limit and limit > 0 else matched
    summary["truncated"] = len(shown) < len(matched)
    summary["items"] = [
        {field: item[field] for field in CANDIDATE_SUMMARY_FIELDS if item.get(field) not in (None, "", [])}
        for item in shown
    ]
    return summary


def merge_candidate_pool(
    data_dir: Path,
    candidates: list[dict[str, Any]],
    source: str = "conversation",
    apply_changes: bool = False,
) -> dict[str, Any]:
    """Store possible-to-watch candidates separately from the user's real watchlist."""
    ensure_data(data_dir)
    pool_path = data_dir / "candidate_pool.json"
    pool = read_json(pool_path)
    existing = pool.get("items", []) if isinstance(pool, dict) else []
    by_title = {canonical_title(item.get("title")): index for index, item in enumerate(existing) if canonical_title(item.get("title"))}
    added = updated = invalid = enriched = 0
    planned = copy.deepcopy(existing)
    for index, raw in enumerate(candidates):
        if not isinstance(raw, dict) or not canonical_title(raw.get("title")):
            invalid += 1
            continue
        candidate = copy.deepcopy(raw)
        before = copy.deepcopy(candidate)
        candidate = enrich_record_metadata(candidate)
        if candidate != before:
            enriched += 1
        key = canonical_title(candidate.get("title"))
        candidate.setdefault("source_tier", "external")
        candidate.setdefault("source", source)
        candidate.setdefault("candidate_id", f"{source}-{key}-{index + 1}")
        candidate.setdefault("candidate_status", "active")
        candidate.setdefault("captured_at", today_iso())
        if key in by_title:
            position = by_title[key]
            merged = copy.deepcopy(planned[position])
            for field, value in candidate.items():
                if value not in (None, "", []):
                    merged[field] = value
            planned[position] = merged
            updated += 1
        else:
            planned.append(candidate)
            by_title[key] = len(planned) - 1
            added += 1
    if apply_changes:
        pool["items"] = planned
        write_json(pool_path, pool)
    return {
        "applied": apply_changes,
        "added": added,
        "updated": updated,
        "invalid": invalid,
        "metadata_enriched_count": enriched,
        "total_after": len(planned),
    }


def build_plan(
    data_dir: Path,
    period: str,
    limit: int | None = None,
    apply_changes: bool = False,
    external_candidates: list[dict[str, Any]] | None = None,
    allow_external: bool = True,
    available_minutes: int | None = None,
    language_mode: str = "normal",
) -> dict[str, Any]:
    ensure_data(data_dir)
    if period not in PLAN_PERIODS:
        raise FilmCuratorError("plan period must be week, month, or season")
    watchlist_path = data_dir / "watchlist.json"
    watchlist = read_json(watchlist_path)
    items = [normalize_item(item) for item in watchlist.get("items", [])]
    profile = read_json(data_dir / "user_profile.json")
    frequency = profile.get("frequency") if profile.get("frequency") in PLAN_CAPACITY else "irregular"
    capacity = max(0, int(limit)) if limit is not None else PLAN_CAPACITY[frequency][period]
    existing = [
        item for item in items
        if not item.get("is_example")
        and item.get("plan_period") == period
        and item.get("status") not in {"watched", "dropped"}
    ]
    available_slots = max(0, capacity - len(existing))
    # Keep a small amount of unassigned capacity for state changes. Explicit limits
    # are treated as an instruction to fill the requested number of slots.
    flex_slots = 0
    if limit is None and period in PLAN_FLEX_RATIO and available_slots > 1:
        flex_slots = max(1, round(available_slots * PLAN_FLEX_RATIO[period]))
    recommendation_slots = max(0, available_slots - flex_slots)
    recent = recent_titles(data_dir)
    candidates: list[dict[str, Any]] = []
    omitted_reasons: list[dict[str, str]] = []
    for item in items:
        if item.get("is_example") or item.get("status") not in {"want", "watching"}:
            continue
        if item.get("plan_period"):
            continue
        if set(item.get("genres") or []) & set(profile.get("avoided_genres") or []):
            omitted_reasons.append({"title": item.get("title", ""), "reason": "命中长期避开类型"})
            continue
        if str(item.get("title", "")).casefold() in recent:
            omitted_reasons.append({"title": item.get("title", ""), "reason": "近14天已看或推荐过"})
            continue
        if available_minutes is not None:
            viewing_minutes = item.get("watch_duration_min") if item.get("content_type") == "series" else item.get("duration_min")
            if viewing_minutes is None or int(viewing_minutes) > available_minutes:
                omitted_reasons.append({"title": item.get("title", ""), "reason": "单次可用时长不匹配或未知"})
                continue
        candidate = copy.deepcopy(item)
        candidate["score"], candidate["score_reasons"] = score_candidate(candidate, profile, recent, "", available_minutes, language_mode)
        candidate["plan_score"] = round(
            candidate["score"]
            + (4 if candidate.get("status") == "watching" else 0)
            + min(4, max(0, int(candidate.get("priority") or 0))) * 0.5,
            2,
        )
        candidates.append(candidate)
    candidates.sort(key=lambda item: (-item["plan_score"], item["title"].casefold()))
    suggestions = diverse_selection(candidates, recommendation_slots) if recommendation_slots else []
    if recommendation_slots and allow_external and len(suggestions) < recommendation_slots:
        external_ranked = rank_candidates(
            data_dir,
            [{**item, "source_tier": "external"} for item in (external_candidates or [])],
            recommendation_slots - len(suggestions),
            "",
            available_minutes,
            language_mode,
        )
        existing_titles = {canonical_title(item.get("title")) for item in suggestions}
        for item in external_ranked:
            if canonical_title(item.get("title")) in existing_titles:
                continue
            item["id"] = item.get("id") or f"external-{canonical_title(item.get('title'))}"
            item["plan_score"] = item.get("score", 0)
            suggestions.append(item)
            existing_titles.add(canonical_title(item.get("title")))
            if len(suggestions) >= recommendation_slots:
                break
    selected_titles = {canonical_title(item.get("title")) for item in suggestions}
    for item in candidates:
        if canonical_title(item.get("title")) not in selected_titles:
            omitted_reasons.append({"title": item.get("title", ""), "reason": "优先级较低或本周期容量已用尽"})
    def schedule_metadata(index: int, total: int) -> tuple[str, str]:
        if period == "month":
            # Spread items across four weeks; a week can contain more than one item
            # when the user's capacity requires it.
            week = min(4, index + 1)
            return f"第{week}周", f"第{week}周的观看安排"
        if period == "season":
            if total <= 1 or index == 0:
                return "入门", "先建立观看兴趣和主题入口"
            if index >= max(2, total - 1):
                return "回望", "回看主题与个人经验的连接"
            return "深入", "进入季度主题的核心作品"
        return f"本周第{index + 1}个观看位", "本周可执行的观看安排"
    if apply_changes and suggestions:
        selected_ids = {item["id"] for item in suggestions}
        for item in watchlist.get("items", []):
            if item.get("id") in selected_ids:
                item["plan_period"] = period
        existing_ids = {item.get("id") for item in watchlist.get("items", [])}
        for item in suggestions:
            if item.get("id") in existing_ids:
                continue
            imported = normalize_item({**item, "id": item.get("id") or str(uuid.uuid4()), "status": "want", "plan_period": period, "source": item.get("source") or "external", "added_date": item.get("added_date") or today_iso()})
            validate_item(imported)
            watchlist.setdefault("items", []).append(imported)
            existing_ids.add(imported.get("id"))
        write_json(watchlist_path, watchlist)
    return {
        "period": period,
        "frequency": frequency,
        "capacity": capacity,
        "existing_count": len(existing),
        "available_slots": available_slots,
        "recommendation_slots": recommendation_slots,
        "flex_slots": flex_slots,
        "available_minutes": available_minutes,
        "existing": [{"id": item["id"], "title": item["title"]} for item in existing],
        "suggestions": [
            {
                "id": item["id"],
                "title": item["title"],
                "content_type": item.get("content_type"),
                "duration_min": item.get("duration_min"),
                "watch_episodes": item.get("watch_episodes"),
                "watch_duration_min": item.get("watch_duration_min"),
                "plan_score": item["plan_score"],
                "score_reasons": item["score_reasons"],
                "source_tier": item.get("source_tier", "library"),
                "schedule_hint": schedule_metadata(index, len(suggestions))[0],
                "schedule_goal": schedule_metadata(index, len(suggestions))[1],
            }
            for index, item in enumerate(suggestions)
        ],
        "omitted_reasons": omitted_reasons,
        "applied": bool(apply_changes),
    }


def canonical_title(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    removable = set(" \t\r\n·•:：-—_（）()《》[]")
    return "".join(character for character in normalized if character not in removable)


def build_summary(data_dir: Path, month: str) -> dict[str, Any]:
    ensure_data(data_dir)
    history = read_json(data_dir / "history.json").get("events", [])
    watchlist = read_json(data_dir / "watchlist.json").get("items", [])
    by_id = {item["id"]: item for item in watchlist}
    events = [
        event for event in history
        if not event.get("is_example") and str(event.get("watched_date", "")).startswith(month)
    ]
    # 历史事件里的分数字段现在叫 work_rating（我的评分）；rating 是合并前的旧写法，
    # 老文件里还有，所以两个都读，否则月度均分会算成空。
    ratings = [
        float(score) for event in events
        if (score := event.get("work_rating", event.get("rating"))) is not None
    ]
    genres: Counter[str] = Counter()
    content_types: Counter[str] = Counter()
    minutes = 0
    for event in events:
        item = by_id.get(event.get("item_id"), {})
        genres.update(item.get("genres") or [])
        if item.get("content_type"):
            content_types[item["content_type"]] += 1
        minutes += int(item.get("duration_min") or 0)
    return {
        "month": month,
        "watched_count": len(events),
        "average_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
        "total_minutes": minutes,
        "top_genres": genres.most_common(5),
        "content_types": dict(content_types),
    }


def validate_data(data_dir: Path) -> list[str]:
    ensure_data(data_dir)
    errors: list[str] = []
    for name in DEFAULT_FILES:
        try:
            payload = read_json(data_dir / name)
            if payload.get("schema_version") != 1:
                errors.append(f"{name}: unsupported schema_version")
        except (FilmCuratorError, AttributeError) as exc:
            errors.append(f"{name}: {exc}")
    try:
        watchlist = read_json(data_dir / "watchlist.json")
        seen: set[str] = set()
        for index, item in enumerate(watchlist.get("items", [])):
            try:
                validate_item(item)
                if item["id"] in seen:
                    errors.append(f"watchlist.json: duplicate id {item['id']}")
                seen.add(item["id"])
            except FilmCuratorError as exc:
                errors.append(f"watchlist.json item {index}: {exc}")
    except FilmCuratorError:
        pass
    return errors


STORAGE_PROVIDERS = ("feishu", "notion")
REQUIRED_TEMPLATE_COLUMNS = {
    "watchlist": ["本地编号", "片名", "状态", "已删除"],
    "history": ["本地编号", "片名", "看完日期", "已删除"],
}


def _empty_storage() -> dict[str, Any]:
    return {"default_provider": "", "feishu": {}, "notion": {}}


def load_storage(data_dir: Path) -> dict[str, Any]:
    ensure_data(data_dir)
    config = read_json(data_dir / "config.json")
    storage = config.get("storage")
    if not isinstance(storage, dict):
        storage = _empty_storage()
    storage.setdefault("default_provider", "")
    storage.setdefault("feishu", {})
    storage.setdefault("notion", {})
    return storage


def save_storage(data_dir: Path, storage: dict[str, Any]) -> dict[str, Any]:
    ensure_data(data_dir)
    config = read_json(data_dir / "config.json")
    config["storage"] = storage
    write_json(data_dir / "config.json", config)
    return storage


def storage_status(data_dir: Path) -> dict[str, Any]:
    storage = load_storage(data_dir)
    bound = [name for name in STORAGE_PROVIDERS if _provider_bound(storage.get(name) or {})]
    default = storage.get("default_provider") or ""
    if default not in bound:
        default = bound[0] if len(bound) == 1 else ""
    needs_choice = len(bound) == 0 or (len(bound) > 1 and not (storage.get("default_provider") in bound))
    return {
        "bound_providers": bound,
        "default_provider": default if not needs_choice or len(bound) == 1 else "",
        "needs_choice": needs_choice,
        "feishu": storage.get("feishu") or {},
        "notion": storage.get("notion") or {},
        "create_name": "Film Curator 观影记录本",
        "tables": {
            "watchlist": BACKEND_TEMPLATE["watchlist"]["name"],
            "history": BACKEND_TEMPLATE["history"]["name"],
        },
    }


def _provider_bound(binding: dict[str, Any]) -> bool:
    if not isinstance(binding, dict):
        return False
    return bool(binding.get("watchlist_url") or binding.get("app_token") or binding.get("watchlist_database_id"))


def bind_storage(
    data_dir: Path,
    provider: str,
    *,
    watchlist_url: str = "",
    history_url: str = "",
    app_token: str = "",
    watchlist_table_id: str = "",
    history_table_id: str = "",
    watchlist_database_id: str = "",
    history_database_id: str = "",
    make_default: bool | None = None,
) -> dict[str, Any]:
    if provider not in STORAGE_PROVIDERS:
        raise FilmCuratorError(f"Unknown storage provider: {provider}")
    storage = load_storage(data_dir)
    binding = {
        "provider": provider,
        "watchlist_url": watchlist_url,
        "history_url": history_url,
        "app_token": app_token,
        "watchlist_table_id": watchlist_table_id,
        "history_table_id": history_table_id,
        "watchlist_database_id": watchlist_database_id,
        "history_database_id": history_database_id,
        "bound_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    storage[provider] = {key: value for key, value in binding.items() if value not in ("", None)}
    storage[provider]["provider"] = provider
    bound = [name for name in STORAGE_PROVIDERS if _provider_bound(storage.get(name) or {})]
    if make_default is True:
        storage["default_provider"] = provider
    elif len(bound) == 1:
        storage["default_provider"] = provider
    elif len(bound) > 1:
        # 两边都有时，第一次自动记下的默认不再算数，要用户再确认一次。
        storage["default_provider"] = ""
    save_storage(data_dir, storage)
    return storage_status(data_dir)


def set_default_storage(data_dir: Path, provider: str) -> dict[str, Any]:
    if provider not in STORAGE_PROVIDERS:
        raise FilmCuratorError(f"Unknown storage provider: {provider}")
    storage = load_storage(data_dir)
    if not _provider_bound(storage.get(provider) or {}):
        raise FilmCuratorError(f"{provider} is not bound yet")
    storage["default_provider"] = provider
    save_storage(data_dir, storage)
    return storage_status(data_dir)


def resolve_storage_provider(data_dir: Path, requested: str = "") -> dict[str, Any]:
    status = storage_status(data_dir)
    if requested:
        if requested not in STORAGE_PROVIDERS:
            raise FilmCuratorError(f"Unknown storage provider: {requested}")
        if requested not in status["bound_providers"] and not requested:
            pass
        return {"provider": requested, "status": status, "ask_user": requested not in status["bound_providers"]}
    if not status["bound_providers"]:
        return {"provider": "", "status": status, "ask_user": True, "reason": "first_use"}
    if len(status["bound_providers"]) == 1:
        return {"provider": status["bound_providers"][0], "status": status, "ask_user": False}
    if status["needs_choice"]:
        return {"provider": "", "status": status, "ask_user": True, "reason": "both_bound"}
    return {"provider": status["default_provider"], "status": status, "ask_user": False}


def feishu_field_specs(table: str) -> list[dict[str, Any]]:
    """飞书建表字段。片名用文本 1，其余按中立类型映射。"""
    specs = []
    for column in BACKEND_TEMPLATE[table]["columns"]:
        field_type = BACKEND_FIELD_TYPES[column["type"]]["feishu"]
        spec: dict[str, Any] = {"field_name": column["name"], "type": field_type}
        if column.get("enum"):
            options = [{"name": VALUE_NAMES[column["enum"]][key]} for key in VALUE_NAMES[column["enum"]]]
            spec["property"] = {"options": options}
        specs.append(spec)
    return specs


def notion_property_specs(table: str) -> dict[str, Any]:
    """Notion 数据库属性。片名作为 title，其余按中立类型映射。"""
    properties: dict[str, Any] = {}
    for column in BACKEND_TEMPLATE[table]["columns"]:
        if column["field"] == "title":
            properties[column["name"]] = {"title": {}}
            continue
        notion_type = BACKEND_FIELD_TYPES[column["type"]]["notion"]
        if notion_type == "select" and column.get("enum"):
            properties[column["name"]] = {
                "select": {"options": [{"name": VALUE_NAMES[column["enum"]][key]} for key in VALUE_NAMES[column["enum"]]]}
            }
        elif notion_type == "multi_select":
            properties[column["name"]] = {"multi_select": {}}
        elif notion_type == "rich_text":
            properties[column["name"]] = {"rich_text": {}}
        else:
            properties[column["name"]] = {notion_type: {}}
    return properties


def diff_template_columns(table: str, existing_names: Iterable[str]) -> dict[str, Any]:
    existing = {str(name) for name in existing_names}
    expected = [column["name"] for column in BACKEND_TEMPLATE[table]["columns"]]
    missing = [name for name in expected if name not in existing]
    extra = sorted(name for name in existing if name not in set(expected))
    required_missing = [name for name in REQUIRED_TEMPLATE_COLUMNS[table] if name not in existing]
    return {
        "table": table,
        "expected": expected,
        "missing": missing,
        "extra": extra,
        "required_missing": required_missing,
        "compatible": not required_missing,
    }


def backend_template() -> dict[str, Any]:
    """云表结构唯一来源：两张表的列定义，加上中立字段类型到飞书/Notion 的落点。"""
    return {
        "field_types": BACKEND_FIELD_TYPES,
        "tables": BACKEND_TEMPLATE,
        "create_name": "Film Curator 观影记录本",
        "feishu": {
            "watchlist_fields": feishu_field_specs("watchlist"),
            "history_fields": feishu_field_specs("history"),
        },
        "notion": {
            "watchlist_properties": notion_property_specs("watchlist"),
            "history_properties": notion_property_specs("history"),
        },
        "required_columns": REQUIRED_TEMPLATE_COLUMNS,
    }


def _column_by_name(table: str, name: str) -> dict[str, Any] | None:
    for column in BACKEND_TEMPLATE[table]["columns"]:
        if column["name"] == name:
            return column
    return None


def _column_by_field(table: str, field: str) -> dict[str, Any] | None:
    for column in BACKEND_TEMPLATE[table]["columns"]:
        if column["field"] == field:
            return column
    return None


def _to_row(table: str, record: dict[str, Any]) -> dict[str, Any]:
    """一条本地记录 → 一行云表。列名用中文，枚举和列表按云表约定整理。"""
    row: dict[str, Any] = {}
    for column in BACKEND_TEMPLATE[table]["columns"]:
        field = column["field"]
        if field == "deleted":
            row[column["name"]] = False
            continue
        value = record.get(field)
        if value is None:
            row[column["name"]] = None
            continue
        if column.get("list"):
            row[column["name"]] = [str(item) for item in value] if isinstance(value, list) else [str(value)]
            continue
        if column.get("enum"):
            row[column["name"]] = VALUE_NAMES[column["enum"]].get(value, value)
            continue
        if column["type"] == "number" and isinstance(value, str):
            row[column["name"]] = parse_scalar(value)
            continue
        row[column["name"]] = value
    return row


def _from_row(table: str, row: dict[str, Any]) -> dict[str, Any]:
    """一行云表 → 内部记录。云表列名翻回内部字段名，枚举和列表译回英文内部值。"""
    record: dict[str, Any] = {}
    for name, value in row.items():
        column = _column_by_name(table, name) or _column_by_field(table, name)
        if column is None:
            continue
        field = column["field"]
        if field == "deleted":
            continue
        if value is None or value == "":
            record[field] = None if column["type"] != "checkbox" else False
            continue
        if column.get("list"):
            if isinstance(value, list):
                record[field] = [str(item).strip() for item in value if str(item).strip()]
            else:
                record[field] = [part.strip() for part in re.split(r"[,，、;；|]", str(value)) if part.strip()]
            continue
        if column.get("enum"):
            record[field] = READ_VALUE_NAMES[column["enum"]].get(value, value)
            continue
        record[field] = value
    return record


def _row_key(row: dict[str, Any]) -> str:
    """从云表行取「本地编号」作为对账钥匙。没填或为空返回空串。"""
    for name in ("本地编号", "id", "item_id"):
        value = row.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def backend_export(data_dir: Path) -> dict[str, Any]:
    """把本地影单和观影历史整理成云表形状，供 AI 通过 MCP 写入飞书/Notion。

    影单只含正式片单；候选池不上云。示例数据一律不带。
    返回结构是 {watchlist: [row, ...], history: [row, ...]}，键名用中文列名。
    """
    ensure_data(data_dir)
    watchlist = read_json(data_dir / "watchlist.json").get("items", [])
    history = read_json(data_dir / "history.json").get("events", [])

    watch_rows: list[dict[str, Any]] = []
    for item in watchlist:
        if item.get("is_example"):
            continue
        watch_rows.append(_to_row("watchlist", item))

    history_rows: list[dict[str, Any]] = []
    for event in history:
        if event.get("is_example"):
            continue
        history_rows.append(_to_row("history", event))

    return {"watchlist": watch_rows, "history": history_rows}


def backend_import(data_dir: Path, input_path: Path) -> dict[str, Any]:
    """把云表拉回的记录写回本地。以「本地编号」对账：新增、更新、按「已删除」标记删除。

    影单只写回正式片单；候选池不在云表里，保持不变。观影历史行用「本地编号」对应
    片单记录，没有编号的行跳过并计数。删除标记优先：标了「已删除」的行不管其他字段，
    直接删本地对应记录。
    """
    ensure_data(data_dir)
    payload = read_raw_json(input_path)
    if not isinstance(payload, dict):
        raise FilmCuratorError("backend import file must be a JSON object with watchlist/history keys")

    watchlist = read_json(data_dir / "watchlist.json")
    history = read_json(data_dir / "history.json")

    watch_items = {str(item.get("id")): item for item in watchlist.get("items", [])}
    history_by_item = {str(event.get("item_id")): event for event in history.get("events", [])}

    added = updated = removed = 0
    skipped_history = 0

    for row in payload.get("watchlist", []):
        if not isinstance(row, dict):
            continue
        key = _row_key(row)
        deleted = bool(row.get("已删除", row.get("deleted", False)))

        if deleted:
            if key and key in watch_items:
                del watch_items[key]
                removed += 1
            continue
        record = _from_row("watchlist", row)
        # 云表里没填本地编号的，当成一条新记录，给它生成本地唯一编号。
        if not key:
            key = str(uuid.uuid4())
        record["id"] = key
        if key in watch_items:
            existing = watch_items[key]
            # 云表可能没有某些列，更新时只覆盖云表里出现过的字段，不抹掉本地独有字段。
            for field, value in record.items():
                if value is not None:
                    existing[field] = value
            updated += 1
        else:
            record.setdefault("added_date", today_iso())
            watch_items[key] = record
            added += 1

    for row in payload.get("history", []):
        if not isinstance(row, dict):
            continue
        key = _row_key(row)
        deleted = bool(row.get("已删除", row.get("deleted", False)))
        if deleted:
            if key and key in history_by_item:
                del history_by_item[key]
                removed += 1
            continue
        if not key:
            skipped_history += 1
            continue
        record = _from_row("history", row)
        record["item_id"] = key
        if key in history_by_item:
            existing = history_by_item[key]
            for field, value in record.items():
                if value is not None:
                    existing[field] = value
            updated += 1
        else:
            if not record.get("title") and key in watch_items:
                record["title"] = watch_items[key].get("title")
            history_by_item[key] = record
            added += 1

    watchlist["items"] = list(watch_items.values())
    history["events"] = list(history_by_item.values())
    write_json(data_dir / "watchlist.json", watchlist)
    write_json(data_dir / "history.json", history)

    profile_refresh = refresh_profile_from_watchlist(data_dir)
    return {
        "added": added,
        "updated": updated,
        "removed": removed,
        "skipped_history": skipped_history,
        "total_watchlist": len(watch_items),
        "total_history": len(history_by_item),
        "validation_errors": validate_data(data_dir),
        "profile_refresh": profile_refresh,
    }


def _count_changes(before: Any, after: Any) -> tuple[int, int]:
    """比较翻译前后，数出改了几个键名、几个取值。"""
    keys = values = 0
    if isinstance(before, dict) and isinstance(after, dict):
        for (key_a, val_a), (key_b, val_b) in zip(before.items(), after.items()):
            if key_a != key_b:
                keys += 1
            sub_keys, sub_values = _count_changes(val_a, val_b)
            keys += sub_keys
            values += sub_values
    elif isinstance(before, list) and isinstance(after, list):
        for item_a, item_b in zip(before, after):
            sub_keys, sub_values = _count_changes(item_a, item_b)
            keys += sub_keys
            values += sub_values
    elif isinstance(before, str) and isinstance(after, str) and before != after:
        values += 1
    return keys, values


def migrate_fields(data_dir: Path, target: str, apply_changes: bool) -> dict[str, Any]:
    """把 data 目录里的字段名和取值整体换成一种语言。不加 --yes 只预演，不写文件。"""
    if target not in FIELD_LANGUAGES:
        raise FilmCuratorError(f"Unsupported field language: {target}")
    ensure_data(data_dir)
    planned: list[dict[str, Any]] = []
    for name in DEFAULT_FILES:
        path = data_dir / name
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise FilmCuratorError(f"{name}: {exc}") from exc
        internal = decode_payload(raw)
        if name == "config.json" and isinstance(internal, dict):
            internal["field_language"] = target
        encoded = encode_payload(internal, target)
        renamed_keys, changed_values = _count_changes(raw, encoded)
        planned.append({
            "file": name, "path": path, "encoded": encoded,
            "renamed_keys": renamed_keys, "changed_values": changed_values,
        })

    summary: dict[str, Any] = {
        "target": target,
        "applied": apply_changes,
        "files": [
            {"file": entry["file"], "renamed_keys": entry["renamed_keys"],
             "changed_values": entry["changed_values"]}
            for entry in planned
        ],
    }
    if not apply_changes:
        summary["note"] = "这是预演，没有写任何文件。确认后加 --yes 再跑一次。"
        return summary

    backup_dir = data_dir / f"backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    for entry in planned:
        (backup_dir / entry["file"]).write_bytes(entry["path"].read_bytes())
    for entry in planned:
        body = json.dumps(entry["encoded"], ensure_ascii=False, indent=2) + "\n"
        entry["path"].write_text(body, encoding="utf-8")
    _FIELD_LANGUAGE_CACHE.clear()

    summary["backup_dir"] = str(backup_dir)
    summary["validation_errors"] = validate_data(data_dir)
    return summary


def emit(value: Any) -> None:
    print(json.dumps(encode_payload(value, active_language()), ensure_ascii=False, indent=2))


def emit_raw(value: Any) -> None:
    """按原样输出，不做字段翻译。云表形状（backend-*）列名和取值已是最终形态。"""
    print(json.dumps(value, ensure_ascii=False, indent=2))


def write_raw_json(path: Path, value: Any) -> None:
    """写文件不翻字段。云表导出文件里的中文列名必须原样落盘。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(body)
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def read_raw_json(path: Path) -> Any:
    """读文件不翻字段。云表拉回的记录用中文列名，不能走 read_json 的翻译。"""
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise FilmCuratorError(f"Missing data file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise FilmCuratorError(f"Invalid JSON in {path}: {exc}") from exc


def enum_arg(table: str, allowed: set[str]):
    """命令行参数中英文都收：--status 已看 与 --status watched 等价。"""

    def convert(value: str) -> str:
        internal = READ_VALUE_NAMES[table].get(value, value)
        if internal not in allowed:
            readable = "、".join(sorted(x for x in allowed if x) + sorted(VALUE_NAMES[table].values()))
            raise argparse.ArgumentTypeError(f"只能是 {readable}")
        return internal

    return convert


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument(
        "--field-language",
        choices=FIELD_LANGUAGES,
        help="本次执行写文件用哪种字段名，不给就按 config.json 的 字段语言",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("init", help="Create missing data files without overwriting existing data")

    add = commands.add_parser("add", help="Add a film or series")
    add.add_argument("--title", required=True)
    add.add_argument("--title-en", default="")
    add.add_argument("--year", type=int)
    add.add_argument("--director", default="")
    add.add_argument("--actors", default="")
    add.add_argument("--country-region", default="")
    add.add_argument("--language", default="")
    add.add_argument("--genres", default="")
    add.add_argument("--content-type", type=enum_arg("content_type", CONTENT_TYPES), default="movie")
    add.add_argument("--duration", type=int)
    add.add_argument("--episode-count", type=int)
    add.add_argument("--watch-episodes", type=int)
    add.add_argument("--watch-duration", type=int)
    add.add_argument("--release-date", default="")
    add.add_argument("--synopsis", default="")
    add.add_argument("--poster-url", default="")
    add.add_argument("--source", default="manual")
    add.add_argument("--reason", default="")
    add.add_argument("--strategy", default="")
    add.add_argument("--status", type=enum_arg("status", ALL_STATUSES))
    add.add_argument("--favorite", action="store_true")
    add.add_argument("--douban-rating", type=float)
    add.add_argument("--tags", default="")
    add.add_argument("--moods", default="")
    add.add_argument("--plan-period", type=enum_arg("plan_period", PLAN_PERIODS | {""}), default="")
    add.add_argument("--priority", type=int, default=0)
    # 「看完了，X 分」是最高频的一句话。给了评分就当成已看，一条命令写完片单、
    # 历史事件和画像学习，不必再 add → 查 id → complete 跑三趟。
    add.add_argument("--work-rating", type=float, help="我的评分 0-10。给了就按已看处理")
    add.add_argument("--fit-rating", type=float, help="当时适配度 0-10，可选")
    add.add_argument("--comment", default="", help="我的短评")
    add.add_argument("--watched-date", default="", help="看完日期，默认今天")

    find = commands.add_parser("find", help="Find items by title using the dedup rules")
    find.add_argument("title")
    find.add_argument("--exact", action="store_true", help="只认规范化后完全同名的记录")

    update = commands.add_parser("update", help="Update arbitrary item fields")
    update.add_argument("item_id")
    update.add_argument("--set", action="append", default=[], required=True, dest="assignments")

    remove = commands.add_parser("remove", help="Remove an item")
    remove.add_argument("item_id")

    complete = commands.add_parser("complete", help="Mark an item watched and learn from its rating")
    complete.add_argument("item_id")
    complete.add_argument("--rating", type=float)
    complete.add_argument("--work-rating", type=float)
    complete.add_argument("--fit-rating", type=float)
    complete.add_argument("--comment", default="")
    complete.add_argument("--feedback-reason", default="")
    complete.add_argument("--session-id", default="")
    complete.add_argument("--date", default=today_iso(), dest="watched_date")

    profile = commands.add_parser("profile", help="Update profile fields")
    profile.add_argument("--set", action="append", default=[], required=True, dest="assignments")

    refresh_profile = commands.add_parser("refresh-profile", help="Recompute profile from all watched records")

    rank = commands.add_parser("rank", help="Rank a JSON array of candidate titles")
    rank.add_argument("--candidates", type=Path, required=True)
    rank.add_argument("--limit", type=int, default=3)
    rank.add_argument("--mood", default="")
    rank.add_argument("--duration", type=int)
    rank.add_argument("--language-mode", choices=("normal", "subtitle_sensitive"), default="normal")

    pool = commands.add_parser("recommend-pool", help="Build a dynamic library-first recommendation pool")
    pool.add_argument("--candidates", type=Path, default=None, help="JSON array of external candidates")
    pool.add_argument("--limit", type=int, default=3)
    pool.add_argument("--mood", default="")
    pool.add_argument("--duration", type=int)
    pool.add_argument("--scope", choices=("dynamic", "library", "external"), default="dynamic")
    pool.add_argument("--no-external", action="store_true", dest="no_external")
    pool.add_argument("--language-mode", choices=("normal", "subtitle_sensitive"), default="normal")
    pool.add_argument("--diagnostics", action="store_true")

    candidate_pool = commands.add_parser("candidate-pool", help="Preview or save possible-to-watch candidates outside the main watchlist")
    candidate_pool.add_argument("--input", type=Path, help="JSON array of possible candidates")
    candidate_pool.add_argument("--source", default="conversation")
    candidate_pool.add_argument("--apply", action="store_true", dest="apply_changes")
    # 不带 --input 时是查阅模式。候选池可能几百条，默认给统计 + 精简字段，
    # 别把整份清单读进上下文。--search 按片名/导演/类型/标签筛，--limit 限条数。
    candidate_pool.add_argument("--search", default="", help="按片名、导演、类型、标签筛选")
    candidate_pool.add_argument("--limit", type=int, default=0, help="最多返回几条，0 为不限")
    candidate_pool.add_argument("--stats", action="store_true", help="只看统计，不返回条目")

    adopt = commands.add_parser("adopt-candidate", help="Add an accepted external candidate to the unified watchlist")
    adopt.add_argument("--candidate", type=Path, required=True)
    adopt.add_argument("--plan-period", type=enum_arg("plan_period", PLAN_PERIODS | {""}), default="")

    feedback_prompts = commands.add_parser("feedback-prompts", help="List or mark one-time follow-up feedback prompts")
    feedback_prompts.add_argument("--mark", dest="mark_item_id", default="")

    session = commands.add_parser("recommend-session", help="Start a recommendation session and return its id")
    session.add_argument("--context", default="")
    session.add_argument("--scope", choices=("dynamic", "library", "external", "theme", "rewatch"), default="dynamic")

    evidence = commands.add_parser("preference-evidence", help="Record an auditable preference observation")
    evidence.add_argument("--signal", required=True)
    evidence.add_argument("--source", default="conversation")
    evidence.add_argument("--reason", default="")
    evidence.add_argument("--item", default="", dest="related_item")
    evidence.add_argument("--confirmed", action="store_true")

    plan = commands.add_parser("plan", help="Preview or apply a capacity-aware viewing plan")
    plan.add_argument("--period", type=enum_arg("plan_period", PLAN_PERIODS), required=True)
    plan.add_argument("--limit", type=int)
    plan.add_argument("--candidates", type=Path, default=None, help="JSON array of external candidates for dynamic plan fill")
    plan.add_argument("--no-external", action="store_true", dest="no_external")
    plan.add_argument("--available-minutes", type=int)
    plan.add_argument("--language-mode", choices=("normal", "subtitle_sensitive"), default="normal")
    plan.add_argument("--apply", action="store_true", dest="apply_changes")

    recommend_log = commands.add_parser("recommend-log", help="Record recommendation exposure or feedback")
    recommend_log.add_argument("--title", required=True)
    recommend_log.add_argument("--strategy", default="precise_match")
    recommend_log.add_argument("--event", choices=("exposed", "accepted", "skipped", "started", "completed", "dropped"), required=True, dest="event_type")
    recommend_log.add_argument("--item-id", default="")
    recommend_log.add_argument("--context", default="")
    recommend_log.add_argument("--date", default=today_iso(), dest="event_date")
    recommend_log.add_argument("--session-id", default="")
    recommend_log.add_argument("--source-tier", choices=("library", "external"), default="")
    recommend_log.add_argument("--feedback-reason", default="")

    summary = commands.add_parser("summary", help="Build a monthly viewing summary")
    summary.add_argument("--month", default=date.today().strftime("%Y-%m"))

    validate = commands.add_parser("validate", help="Validate all data files")
    validate.add_argument("--quiet", action="store_true")

    migrate = commands.add_parser("migrate-fields", help="Rewrite data files with Chinese or English field names")
    migrate.add_argument("--to", choices=FIELD_LANGUAGES, required=True, dest="target_language")
    migrate.add_argument("--yes", action="store_true", dest="apply_changes")

    commands.add_parser("backend-template", help="Print the cloud table template for Feishu/Notion")
    backend_export_cmd = commands.add_parser("backend-export", help="Export local watchlist/history as cloud-table rows")
    backend_export_cmd.add_argument("--output", type=Path, help="Write to a file instead of stdout")
    backend_import_cmd = commands.add_parser("backend-import", help="Merge cloud-table rows back into local data")
    backend_import_cmd.add_argument("--input", type=Path, required=True)

    storage_status_cmd = commands.add_parser("storage-status", help="Show Feishu/Notion binding status")
    bind = commands.add_parser("storage-bind", help="Remember a Feishu or Notion watchlist binding")
    bind.add_argument("--provider", choices=STORAGE_PROVIDERS, required=True)
    bind.add_argument("--watchlist-url", default="")
    bind.add_argument("--history-url", default="")
    bind.add_argument("--app-token", default="")
    bind.add_argument("--watchlist-table-id", default="")
    bind.add_argument("--history-table-id", default="")
    bind.add_argument("--watchlist-database-id", default="")
    bind.add_argument("--history-database-id", default="")
    bind.add_argument("--default", action="store_true", dest="make_default")

    storage_default = commands.add_parser("storage-default", help="Set the default cloud provider")
    storage_default.add_argument("--provider", choices=STORAGE_PROVIDERS, required=True)

    check_columns = commands.add_parser("storage-check-columns", help="Compare existing cloud columns with the template")
    check_columns.add_argument("--table", choices=("watchlist", "history"), required=True)
    check_columns.add_argument("--columns", required=True, help="Comma-separated existing column names")
    return parser


def main(argv: list[str] | None = None) -> int:
    global ACTIVE_DATA_DIR, FIELD_LANGUAGE_OVERRIDE
    args = build_parser().parse_args(argv)
    data_dir: Path = args.data_dir.resolve()
    ACTIVE_DATA_DIR = data_dir
    FIELD_LANGUAGE_OVERRIDE = args.field_language
    try:
        if args.command not in {
            "init", "backend-template", "backend-export", "backend-import",
            "storage-status", "storage-bind", "storage-default", "storage-check-columns",
        }:
            auto_enrich_missing_metadata(data_dir)
        if args.command == "init":
            emit({"created": ensure_data(data_dir), "data_dir": str(data_dir)})
        elif args.command == "add":
            watched = args.work_rating is not None or args.fit_rating is not None
            created = add_item(data_dir, {
                "title": args.title, "title_en": args.title_en, "year": args.year,
                "director": args.director, "genres": split_csv(args.genres),
                "actors": split_csv(args.actors), "country_region": args.country_region,
                "language": args.language,
                "content_type": args.content_type, "duration_min": args.duration,
                "episode_count": args.episode_count, "release_date": args.release_date,
                "watch_episodes": args.watch_episodes, "watch_duration_min": args.watch_duration,
                "synopsis": args.synopsis, "poster_url": args.poster_url,
                "source": args.source, "recommend_reason": args.reason,
                "strategy_tag": args.strategy,
                "status": args.status or ("watched" if watched else None),
                "favorite": args.favorite, "douban_rating": args.douban_rating,
                "tags": split_csv(args.tags),
                "moods": split_csv(args.moods), "plan_period": args.plan_period,
                "priority": args.priority,
            })
            # 带了评分就顺手走完 complete：写历史事件、推荐反馈、重算画像。
            # 这样调用方不必先读文件拿 id 再跑第二条命令。
            if watched:
                created = complete_item(
                    data_dir, created["id"], None, args.comment,
                    args.watched_date or today_iso(),
                    args.work_rating, args.fit_rating, "", "",
                )
            emit(created)
        elif args.command == "find":
            emit(find_items_by_title(data_dir, args.title, args.exact))
        elif args.command == "update":
            emit(update_item(data_dir, args.item_id, parse_assignments(args.assignments, ITEM_WRITABLE_FIELDS)))
        elif args.command == "remove":
            emit(remove_item(data_dir, args.item_id))
        elif args.command == "complete":
            emit(complete_item(
                data_dir, args.item_id, args.rating, args.comment, args.watched_date,
                args.work_rating, args.fit_rating, args.feedback_reason, args.session_id,
            ))
        elif args.command == "profile":
            emit(update_profile(data_dir, parse_assignments(args.assignments)))
        elif args.command == "refresh-profile":
            emit(refresh_profile_from_watchlist(data_dir))
        elif args.command == "rank":
            candidates = read_json(args.candidates)
            if not isinstance(candidates, list):
                raise FilmCuratorError("candidates file must contain a JSON array")
            emit(rank_candidates(data_dir, candidates, args.limit, args.mood, args.duration, args.language_mode))
        elif args.command == "recommend-pool":
            candidates = load_external_candidates(args.candidates) if args.candidates else load_candidate_pool(data_dir)
            if args.diagnostics and args.scope == "external":
                emit(recommendation_diagnostics(data_dir, candidates, args.limit, args.mood, args.duration, args.language_mode))
            else:
                emit(build_recommendation_pool(
                    data_dir, candidates, args.limit, args.mood, args.duration,
                    not args.no_external, args.scope, args.language_mode,
                ))
        elif args.command == "candidate-pool":
            if args.input:
                candidates = load_external_candidates(args.input)
                emit(merge_candidate_pool(data_dir, candidates, args.source, args.apply_changes))
            else:
                emit(survey_candidate_pool(data_dir, args.search, args.limit, args.stats))
        elif args.command == "adopt-candidate":
            payload = read_json(args.candidate)
            candidate = payload.get("candidate", payload) if isinstance(payload, dict) else {}
            if not isinstance(candidate, dict):
                raise FilmCuratorError("candidate file must contain a JSON object")
            emit(adopt_candidate(data_dir, candidate, args.plan_period))
        elif args.command == "feedback-prompts":
            if args.mark_item_id:
                emit({"marked": args.mark_item_id, "prompted_item_ids": mark_feedback_prompted(data_dir, args.mark_item_id)})
            else:
                emit({"pending": feedback_prompt_candidates(data_dir)})
        elif args.command == "recommend-session":
            emit(create_recommendation_session(data_dir, args.context, args.scope))
        elif args.command == "preference-evidence":
            emit(record_preference_evidence(data_dir, args.signal, args.source, args.reason, args.related_item, args.confirmed))
        elif args.command == "plan":
            candidates = load_external_candidates(args.candidates) if args.candidates else load_candidate_pool(data_dir)
            emit(build_plan(data_dir, args.period, args.limit, args.apply_changes, candidates, not args.no_external, args.available_minutes, args.language_mode))
        elif args.command == "recommend-log":
            emit(log_recommendation(
                data_dir,
                args.title,
                args.strategy,
                args.event_type,
                args.item_id,
                args.context,
                args.event_date,
                args.session_id,
                args.source_tier,
                args.feedback_reason,
            ))
        elif args.command == "summary":
            emit(build_summary(data_dir, args.month))
        elif args.command == "validate":
            errors = validate_data(data_dir)
            if errors:
                if not args.quiet:
                    emit({"valid": False, "errors": errors})
                return 1
            if not args.quiet:
                emit({"valid": True, "errors": []})
        elif args.command == "migrate-fields":
            emit(migrate_fields(data_dir, args.target_language, args.apply_changes))
        elif args.command == "backend-template":
            emit_raw(backend_template())
        elif args.command == "backend-export":
            payload = backend_export(data_dir)
            if args.output:
                write_raw_json(args.output.resolve(), payload)
                emit_raw({"output": str(args.output.resolve()), "watchlist_rows": len(payload["watchlist"]), "history_rows": len(payload["history"])})
            else:
                emit_raw(payload)
        elif args.command == "backend-import":
            emit_raw(backend_import(data_dir, args.input.resolve()))
        elif args.command == "storage-status":
            emit_raw(storage_status(data_dir))
        elif args.command == "storage-bind":
            emit_raw(bind_storage(
                data_dir, args.provider,
                watchlist_url=args.watchlist_url,
                history_url=args.history_url,
                app_token=args.app_token,
                watchlist_table_id=args.watchlist_table_id,
                history_table_id=args.history_table_id,
                watchlist_database_id=args.watchlist_database_id,
                history_database_id=args.history_database_id,
                make_default=True if args.make_default else None,
            ))
        elif args.command == "storage-default":
            emit_raw(set_default_storage(data_dir, args.provider))
        elif args.command == "storage-check-columns":
            emit_raw(diff_template_columns(args.table, split_csv(args.columns)))
        return 0
    except FilmCuratorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
