#!/usr/bin/env python3
"""Deterministic data operations for the Film Curator skill."""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import tempfile
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
METADATA_LOOKUP_TIMEOUT = 4.0
WIKIDATA_API_URL = "https://www.wikidata.org/w/api.php"
WIKIPEDIA_SUMMARY_URL = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}"

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
    "user_rating": "我的评分",
    "work_rating": "作品评价",
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
    },
    "recommend_log.json": {"schema_version": 1, "events": []},
    "preference_evidence.json": {"schema_version": 1, "events": []},
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


def enrich_record_metadata(record: dict[str, Any]) -> dict[str, Any]:
    item = copy.deepcopy(record or {})
    title = str(item.get("title") or "").strip()
    if not title:
        return item
    needs_lookup = any(
        not item.get(field)
        for field in ("synopsis", "genres", "content_type", "director", "duration_min", "language", "country_region", "release_date", "title_en")
    )
    if not needs_lookup:
        return item
    metadata = lookup_online_metadata(title, item.get("year"))
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
        if field == "release_date":
            if not item.get("release_date"):
                item["release_date"] = value
            continue
        if field == "poster_url":
            if not item.get("poster_url"):
                item["poster_url"] = value
            continue
        if field == "content_type":
            if not item.get("content_type") or item.get("content_type") == "movie":
                item["content_type"] = value
            continue
        if field in {"director", "language", "country_region", "synopsis"}:
            if not item.get(field):
                item[field] = value
    return item


def _metadata_fields_missing(item: dict[str, Any]) -> list[str]:
    fields = ("synopsis", "genres", "content_type", "director", "duration_min", "language", "country_region", "release_date", "title_en")
    return [field for field in fields if not item.get(field)]


def auto_enrich_missing_metadata(data_dir: Path) -> dict[str, Any]:
    """Retry metadata lookup for items that still have obvious missing facts."""
    ensure_data(data_dir)
    sources = {
        "watchlist": data_dir / "watchlist.json",
        "candidatePool": data_dir / "candidate_pool.json",
    }
    updated_files: set[str] = set()
    checked = updated = 0
    for file_name, path in sources.items():
        payload = read_json(path)
        items = payload.get("items", []) if isinstance(payload, dict) else []
        changed = False
        for index, item in enumerate(items):
            if not isinstance(item, dict) or not str(item.get("title") or "").strip():
                continue
            missing = _metadata_fields_missing(item)
            if not missing:
                continue
            checked += 1
            enriched = enrich_record_metadata(item)
            if enriched != item:
                items[index] = enriched
                changed = True
                updated += 1
        if changed and isinstance(payload, dict):
            payload["items"] = items
            write_json(path, payload)
            updated_files.add(file_name)
    if updated_files:
        export_web(data_dir, data_dir.parent / "web" / "data.js")
    return {"checked": checked, "updated": updated, "updated_files": sorted(updated_files)}


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


def parse_assignments(values: Iterable[str]) -> dict[str, Any]:
    """--set 支持中文字段名和中文取值：状态=已看 与 status=watched 等价。"""
    updates: dict[str, Any] = {}
    for assignment in values:
        if "=" not in assignment:
            raise FilmCuratorError(f"Expected FIELD=VALUE, got {assignment!r}")
        field, raw = assignment.split("=", 1)
        field = field.strip()
        if not field:
            raise FilmCuratorError("Field name cannot be empty")
        internal = READ_FIELD_NAMES.get(field, field)
        table = ENUM_FIELDS.get(internal)
        value = parse_scalar(raw)
        updates[internal] = _convert_value(value, table, "decode") if table else value
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
    for field in ("user_rating", "work_rating", "fit_rating", "douban_rating"):
        rating = item.get(field)
        if rating is not None and not 0 <= float(rating) <= 10:
            raise FilmCuratorError(f"{field_label(field)} must be between 0 and 10")


def find_item(items: list[dict[str, Any]], item_id: str) -> dict[str, Any]:
    for item in items:
        if item.get("id") == item_id:
            return item
    raise FilmCuratorError(f"Unknown item id: {item_id}")


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
        "user_rating": values.get("user_rating"),
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
    profile.setdefault("genre_weights", {})
    delta = 0.2 if rating >= 8 else (-0.2 if rating <= 5 else 0.05)
    for genre in item.get("genres", []):
        current = float(profile["genre_weights"].get(genre, 0))
        profile["genre_weights"][genre] = round(max(-2.0, min(2.0, current + delta)), 2)
    profile["ratings_count"] = int(profile.get("ratings_count", 0)) + 1
    if rating >= 8:
        profile["high_ratings_count"] = int(profile.get("high_ratings_count", 0)) + 1
    profile["last_updated"] = today_iso()


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
    if rating is not None and not 0 <= rating <= 10:
        raise FilmCuratorError("rating must be between 0 and 10")
    for name, value in (("work_rating", work_rating), ("fit_rating", fit_rating)):
        if value is not None and not 0 <= value <= 10:
            raise FilmCuratorError(f"{name} must be between 0 and 10")
    if rating is None and work_rating is not None:
        rating = work_rating
    item = update_item(
        data_dir,
        item_id,
        {
            "status": "watched",
            "watched_date": watched_date,
            "user_rating": rating,
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
            "rating": rating,
            "work_rating": work_rating,
            "fit_rating": fit_rating,
            "comment": comment,
            "feedback_reason": feedback_reason,
            "session_id": session_id,
        }
    )
    write_json(history_path, history)

    if rating is not None:
        profile_path = data_dir / "user_profile.json"
        profile = read_json(profile_path)
        learn_from_rating(profile, item, rating)
        write_json(profile_path, profile)

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
        if candidate_duration is None:
            return "duration_unknown"
        if int(candidate_duration) > duration:
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


def extract_import_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get("items"), list):
        return payload["items"]
    watchlist = payload.get("watchlist")
    if isinstance(watchlist, dict) and isinstance(watchlist.get("items"), list):
        return watchlist["items"]
    return []


def analyze_import(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> dict[str, Any]:
    known: dict[str, dict[str, Any]] = {}
    for item in existing:
        key = canonical_title(item.get("title"))
        if key and key not in known:
            known[key] = item
    new_items: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    for index, item in enumerate(incoming):
        key = canonical_title(item.get("title") if isinstance(item, dict) else "")
        if not key:
            invalid.append({"index": index, "reason": "缺少片名"})
            continue
        if key in known:
            duplicates.append({
                "index": index,
                "incoming_title": item.get("title"),
                "existing_title": known[key].get("title"),
                "existing_id": known[key].get("id"),
            })
        else:
            new_items.append(item)
            known[key] = item
    return {
        "total": len(incoming),
        "new_count": len(new_items),
        "duplicate_count": len(duplicates),
        "invalid_count": len(invalid),
        "duplicates": duplicates,
        "invalid": invalid,
    }


def _unique_import_id(preferred: Any, used: set[str], seed: str) -> str:
    base = str(preferred or f"import-{seed}").strip() or f"import-{seed}"
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}-{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def merge_import_items(
    existing: list[dict[str, Any]], incoming: list[dict[str, Any]], policy: str
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    if policy not in {"skip", "keep", "replace"}:
        raise FilmCuratorError(f"Unsupported duplicate policy: {policy}")
    result = [normalize_item(item) for item in existing]
    used_ids = {str(item.get("id")) for item in result if item.get("id")}
    stats = {"added": 0, "skipped": 0, "updated": 0, "invalid": 0}
    for index, raw in enumerate(incoming):
        if not isinstance(raw, dict) or not canonical_title(raw.get("title")):
            stats["invalid"] += 1
            continue
        key = canonical_title(raw["title"])
        match_index = next(
            (position for position, item in enumerate(result) if canonical_title(item.get("title")) == key),
            None,
        )
        if match_index is not None and policy == "skip":
            stats["skipped"] += 1
            continue
        if match_index is not None and policy == "replace":
            item_id = result[match_index].get("id")
            result[match_index].update(copy.deepcopy(raw))
            result[match_index]["id"] = item_id
            result[match_index] = normalize_item(result[match_index])
            validate_item(result[match_index])
            stats["updated"] += 1
            continue
        item = normalize_item(raw)
        item["id"] = _unique_import_id(item.get("id"), used_ids, f"{key}-{index + 1}")
        validate_item(item)
        result.append(item)
        stats["added"] += 1
    return result, stats


def import_data(
    data_dir: Path,
    input_path: Path,
    policy: str,
    apply_changes: bool,
    enrich_metadata: bool = True,
) -> dict[str, Any]:
    ensure_data(data_dir)
    payload = read_json(input_path)
    incoming = extract_import_items(payload)
    if not incoming:
        raise FilmCuratorError("Import file does not contain watchlist items")
    metadata_enriched_count = 0
    if enrich_metadata:
        enriched: list[dict[str, Any]] = []
        for raw in incoming:
            if not isinstance(raw, dict):
                enriched.append(raw)
                continue
            before = copy.deepcopy(raw)
            after = enrich_record_metadata(raw)
            if after != before:
                metadata_enriched_count += 1
            enriched.append(after)
        incoming = enriched
    watchlist_path = data_dir / "watchlist.json"
    watchlist = read_json(watchlist_path)
    analysis = analyze_import(watchlist.get("items", []), incoming)
    response: dict[str, Any] = {
        "analysis": analysis,
        "applied": False,
        "policy": policy,
        "metadata_enriched_count": metadata_enriched_count,
    }
    if apply_changes:
        merged, stats = merge_import_items(watchlist.get("items", []), incoming, policy)
        watchlist["items"] = merged
        write_json(watchlist_path, watchlist)
        history_path = data_dir / "history.json"
        history = read_json(history_path)
        known_history = {event.get("item_id") for event in history.get("events", [])}
        for item in merged:
            if item.get("status") != "watched" or item.get("id") in known_history:
                continue
            event = {
                "item_id": item["id"],
                "title": item["title"],
                "watched_date": item.get("watched_date") or today_iso(),
                "rating": item.get("user_rating"),
                "comment": item.get("user_comment") or "",
            }
            if item.get("is_example"):
                event["is_example"] = True
            history["events"].append(event)
        write_json(history_path, history)
        response.update({"applied": True, "stats": stats, "total_after": len(merged)})
    return response


def build_summary(data_dir: Path, month: str) -> dict[str, Any]:
    ensure_data(data_dir)
    history = read_json(data_dir / "history.json").get("events", [])
    watchlist = read_json(data_dir / "watchlist.json").get("items", [])
    by_id = {item["id"]: item for item in watchlist}
    events = [
        event for event in history
        if not event.get("is_example") and str(event.get("watched_date", "")).startswith(month)
    ]
    ratings = [float(event["rating"]) for event in events if event.get("rating") is not None]
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


def export_web(data_dir: Path, destination: Path) -> Path:
    ensure_data(data_dir)
    payload = {
        "profile": read_json(data_dir / "user_profile.json"),
        "watchlist": read_json(data_dir / "watchlist.json"),
        "candidatePool": read_json(data_dir / "candidate_pool.json"),
        "history": read_json(data_dir / "history.json"),
        "config": read_json(data_dir / "config.json"),
        "recommendLog": read_json(data_dir / "recommend_log.json"),
        "preferenceEvidence": read_json(data_dir / "preference_evidence.json"),
        "exportedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(encode_payload(payload, field_language(data_dir)), ensure_ascii=False, indent=2)
    destination.write_text(f"window.FILM_DATA = {serialized};\n", encoding="utf-8")
    return destination


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
    summary["web_data"] = str(export_web(data_dir, data_dir.parent / "web" / "data.js"))
    return summary


def emit(value: Any) -> None:
    print(json.dumps(encode_payload(value, active_language()), ensure_ascii=False, indent=2))


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

    export = commands.add_parser("export-web", help="Regenerate web/data.js")
    export.add_argument("--output", type=Path, default=ROOT / "web" / "data.js")

    migrate = commands.add_parser("migrate-fields", help="Rewrite data files with Chinese or English field names")
    migrate.add_argument("--to", choices=FIELD_LANGUAGES, required=True, dest="target_language")
    migrate.add_argument("--yes", action="store_true", dest="apply_changes")

    import_command = commands.add_parser("import-data", help="Preview or merge an exported watchlist")
    import_command.add_argument("--input", type=Path, required=True)
    import_command.add_argument("--duplicate-policy", choices=("skip", "keep", "replace"), default="skip")
    import_command.add_argument("--apply", action="store_true", dest="apply_changes")
    import_command.add_argument("--no-enrich", action="store_true", dest="no_enrich")
    return parser


def main(argv: list[str] | None = None) -> int:
    global ACTIVE_DATA_DIR, FIELD_LANGUAGE_OVERRIDE
    args = build_parser().parse_args(argv)
    data_dir: Path = args.data_dir.resolve()
    ACTIVE_DATA_DIR = data_dir
    FIELD_LANGUAGE_OVERRIDE = args.field_language
    try:
        if args.command != "init" and not (args.command == "import-data" and getattr(args, "no_enrich", False)):
            auto_enrich_missing_metadata(data_dir)
        if args.command == "init":
            emit({"created": ensure_data(data_dir), "data_dir": str(data_dir)})
        elif args.command == "add":
            emit(add_item(data_dir, {
                "title": args.title, "title_en": args.title_en, "year": args.year,
                "director": args.director, "genres": split_csv(args.genres),
                "actors": split_csv(args.actors), "country_region": args.country_region,
                "language": args.language,
                "content_type": args.content_type, "duration_min": args.duration,
                "episode_count": args.episode_count, "release_date": args.release_date,
                "watch_episodes": args.watch_episodes, "watch_duration_min": args.watch_duration,
                "synopsis": args.synopsis, "poster_url": args.poster_url,
                "source": args.source, "recommend_reason": args.reason,
                "strategy_tag": args.strategy, "status": args.status,
                "favorite": args.favorite, "douban_rating": args.douban_rating,
                "tags": split_csv(args.tags),
                "moods": split_csv(args.moods), "plan_period": args.plan_period,
                "priority": args.priority,
            }))
        elif args.command == "update":
            emit(update_item(data_dir, args.item_id, parse_assignments(args.assignments)))
        elif args.command == "remove":
            emit(remove_item(data_dir, args.item_id))
        elif args.command == "complete":
            emit(complete_item(
                data_dir, args.item_id, args.rating, args.comment, args.watched_date,
                args.work_rating, args.fit_rating, args.feedback_reason, args.session_id,
            ))
        elif args.command == "profile":
            emit(update_profile(data_dir, parse_assignments(args.assignments)))
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
                emit({"items": load_candidate_pool(data_dir)})
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
        elif args.command == "export-web":
            emit({"output": str(export_web(data_dir, args.output.resolve()))})
        elif args.command == "import-data":
            emit(import_data(data_dir, args.input.resolve(), args.duplicate_policy, args.apply_changes, not args.no_enrich))
        elif args.command == "migrate-fields":
            emit(migrate_fields(data_dir, args.target_language, args.apply_changes))
        return 0
    except FilmCuratorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
