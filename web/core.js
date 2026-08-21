(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.FilmCore = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const STATUS_LABELS = {
    want: "待看",
    watching: "在看",
    watched: "已看",
    dropped: "已弃"
  };
  const TYPE_LABELS = {
    movie: "电影",
    series: "剧集",
    documentary: "纪录片",
    animation: "动画",
    short: "短片"
  };
  const TERM_LABELS = {
    drama: "剧情",
    comedy: "喜剧",
    romance: "爱情",
    mystery: "悬疑",
    crime: "犯罪",
    thriller: "惊悚",
    sci_fi: "科幻",
    sciencefiction: "科幻",
    sciencefictionfilm: "科幻",
    fantasy: "奇幻",
    animation: "动画",
    animated: "动画",
    documentary: "纪录片",
    family: "家庭",
    history: "历史",
    war: "战争",
    music: "音乐",
    musical: "音乐",
    adventure: "冒险",
    action: "动作",
    horror: "恐怖",
    biography: "传记",
    short: "短片",
    english: "英语",
    chinese: "中文",
    mandarin: "普通话",
    cantonese: "粤语",
    japanese: "日语",
    korean: "韩语",
    french: "法语",
    german: "德语",
    spanish: "西班牙语",
    italian: "意大利语",
    russian: "俄语",
    hindi: "印地语",
    portuguese: "葡萄牙语",
    arabic: "阿拉伯语",
    subtitle_sensitive: "不方便一直盯字幕",
    any: "都可以"
  };

  const FIELD_NAMES = {
    schema_version: "结构版本",
    items: "记录",
    events: "事件",
    is_example: "示例数据",
    id: "记录ID",
    title: "片名",
    title_en: "英文名",
    year: "年份",
    director: "导演",
    actors: "主演",
    country_region: "国家地区",
    language: "语言",
    genres: "类型",
    tags: "自定义标签",
    moods: "情绪",
    content_type: "内容类型",
    duration_min: "时长分钟",
    episode_count: "集数",
    watch_episodes: "本次看几集",
    watch_duration_min: "本次预计时长",
    release_date: "上映日期",
    douban_rating: "豆瓣评分",
    user_rating: "我的评分",
    work_rating: "作品评价",
    fit_rating: "当时适配度",
    status: "状态",
    favorite: "最爱",
    plan_period: "计划周期",
    priority: "优先级",
    synopsis: "简介",
    recommend_reason: "推荐理由",
    user_comment: "我的短评",
    poster_url: "图片地址",
    source: "来源",
    source_tier: "来源层级",
    candidate_id: "候选ID",
    added_date: "加入日期",
    watched_date: "看完日期",
    strategy_tag: "策略标签",
    frequency: "观影频率",
    preferred_genres: "偏好类型",
    avoided_genres: "避开类型",
    preferred_languages: "偏好语言",
    avoided_languages: "避开语言",
    subtitle_mode: "字幕场景",
    narrative_pace: "叙事节奏",
    desired_mood: "想要的情绪",
    av_preference: "视听偏好",
    favorite_directors: "喜欢的导演",
    favorite_actors: "喜欢的演员",
    top_films: "最爱影片",
    genre_weights: "类型权重",
    ratings_count: "评分次数",
    high_ratings_count: "高分次数",
    last_updated: "最后更新",
    onboarding_stage: "引导阶段",
    feedback_prompted_item_ids: "已问过反馈的记录ID",
    app_name: "记录本名称",
    theme: "主题",
    depth_level: "赏析深度",
    default_sort: "默认排序",
    week_starts_monday: "周一作为一周开始",
    field_options: "候选项",
    saved_views: "自定义视图",
    filters: "筛选条件",
    statuses: "状态列表",
    contentType: "内容类型筛选",
    planPeriod: "计划周期筛选",
    minRating: "最低评分",
    genreQuery: "类型或标签包含",
    field_language: "字段语言",
    item_id: "对应记录ID",
    session_id: "会话ID",
    rating: "评分",
    comment: "短评",
    strategy: "策略",
    feedback: "反馈",
    feedback_reason: "反馈理由",
    event_type: "事件类型",
    date: "日期",
    scope: "范围",
    context: "当时情况",
    signal: "观察到的偏好",
    related_item: "相关影片",
    confirmed: "已确认",
    reason: "理由"
  };

  const FIELD_NAME_ALIASES = {
    "记录 ID": "id",
    "国家/地区": "country_region",
    "时长（分钟）": "duration_min",
    "标签": "tags",
    "视图ID": "id",
    "视图名称": "name"
  };

  const SUBTREE_FIELD_OVERRIDES = {
    saved_views: { id: "视图ID", name: "视图名称" }
  };

  const ENUM_FIELDS = {
    content_type: "content_type",
    status: "status",
    plan_period: "plan_period",
    statuses: "status",
    contentType: "content_type",
    planPeriod: "plan_period"
  };

  const VALUE_NAMES = {
    content_type: {
      movie: "电影",
      series: "剧集",
      documentary: "纪录片",
      animation: "动画",
      short: "短片"
    },
    status: {
      want: "待看",
      watching: "在看",
      watched: "已看",
      dropped: "已弃"
    },
    plan_period: {
      week: "本周",
      month: "本月",
      season: "本季"
    }
  };

  const VALUE_ALIASES = {
    status: {
      planned: "want",
      paused: "want",
      想看: "want",
      看完: "watched",
      弃看: "dropped",
      在看: "watching"
    }
  };

  const OPAQUE_KEYS = new Set(["genre_weights"]);

  const READ_FIELD_NAMES = (function () {
    const names = {};
    Object.keys(FIELD_NAMES).forEach(function (internal) {
      names[FIELD_NAMES[internal]] = internal;
      names[internal] = internal;
    });
    Object.keys(FIELD_NAME_ALIASES).forEach(function (alias) {
      names[FIELD_NAME_ALIASES[alias]] = FIELD_NAME_ALIASES[alias];
      names[alias] = FIELD_NAME_ALIASES[alias];
    });
    return names;
  })();

  const READ_VALUE_NAMES = (function () {
    const values = {};
    Object.keys(VALUE_NAMES).forEach(function (table) {
      const reverse = {};
      Object.keys(VALUE_NAMES[table]).forEach(function (internal) {
        reverse[VALUE_NAMES[table][internal]] = internal;
        reverse[internal] = internal;
      });
      Object.keys(VALUE_ALIASES[table] || {}).forEach(function (alias) {
        reverse[alias] = VALUE_ALIASES[table][alias];
      });
      values[table] = reverse;
    });
    return values;
  })();

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function convertValue(value, table, direction) {
    if (Array.isArray(value)) return value.map(function (item) { return convertValue(item, table, direction); });
    if (typeof value !== "string" || !value) return value;
    const internal = READ_VALUE_NAMES[table] && Object.prototype.hasOwnProperty.call(READ_VALUE_NAMES[table], value)
      ? READ_VALUE_NAMES[table][value]
      : value;
    if (direction === "decode") return internal;
    return VALUE_NAMES[table] && Object.prototype.hasOwnProperty.call(VALUE_NAMES[table], internal)
      ? VALUE_NAMES[table][internal]
      : internal;
  }

  function convertNode(node, direction, fieldNames) {
    if (Array.isArray(node)) {
      return node.map(function (child) { return convertNode(child, direction, fieldNames); });
    }
    if (!node || typeof node !== "object") return node;
    const result = {};
    Object.keys(node).forEach(function (key) {
      const internal = Object.prototype.hasOwnProperty.call(READ_FIELD_NAMES, key) ? READ_FIELD_NAMES[key] : key;
      const resultKey = direction === "encode" ? (fieldNames[internal] || internal) : internal;
      const child = node[key];
      if (OPAQUE_KEYS.has(internal)) {
        result[resultKey] = clone(child);
        return;
      }
      const table = ENUM_FIELDS[internal];
      if (table) {
        result[resultKey] = convertValue(child, table, direction);
        return;
      }
      const childNames = SUBTREE_FIELD_OVERRIDES[internal]
        ? Object.assign({}, fieldNames, SUBTREE_FIELD_OVERRIDES[internal])
        : fieldNames;
      result[resultKey] = convertNode(child, direction, childNames);
    });
    return result;
  }

  function decodePayload(payload) {
    return convertNode(payload, "decode", FIELD_NAMES);
  }

  function encodePayload(payload, language) {
    if (language === "en") return decodePayload(payload);
    return convertNode(payload, "encode", FIELD_NAMES);
  }

  function migratedStatus(value) {
    if (value === "planned" || value === "paused") return "want";
    return Object.prototype.hasOwnProperty.call(STATUS_LABELS, value) ? value : "want";
  }

  function normalizeItem(raw, index) {
    const item = Object.assign({}, raw || {});
    delete item.zone;
    delete item.watch_cue;
    return Object.assign({
      id: "local-" + index,
      title: "未命名影片",
      title_en: "",
      actors: [],
      country_region: "",
      language: "",
      genres: [],
      tags: [],
      moods: [],
      content_type: "movie",
      release_date: "",
      episode_count: null,
      watch_episodes: null,
      watch_duration_min: null,
      status: "want",
      favorite: false,
      plan_period: "",
      priority: 0,
      added_date: "",
      douban_rating: null,
      user_rating: null,
      work_rating: null,
      fit_rating: null,
      user_comment: ""
    }, item, {
      status: migratedStatus(item.status),
      favorite: Boolean(item.favorite),
      plan_period: item.plan_period || "",
      genres: Array.isArray(item.genres) ? item.genres : [],
      tags: Array.isArray(item.tags) ? item.tags : [],
      moods: Array.isArray(item.moods) ? item.moods : [],
      actors: Array.isArray(item.actors) ? item.actors : []
    });
  }

  function displayTerm(value) {
    const text = String(value == null ? "" : value).trim();
    if (!text) return "";
    if (/[\/,，;；|]/.test(text)) {
      return text.split(/[\/,，;；|]/).map(function (part) { return displayTerm(part); }).filter(Boolean).join(" / ");
    }
    const compact = text.normalize("NFKC").toLocaleLowerCase().replace(/[\s·•:：\-—_（）()《》\[\]]+/g, "");
    return TERM_LABELS[compact] || text;
  }

  function displayTerms(values) {
    return (values || []).map(displayTerm).filter(Boolean);
  }

  function normalize(payload) {
    const result = decodePayload(clone(payload || {}));
    result.profile = result.profile || {};
    result.profile.preferred_genres = Array.isArray(result.profile.preferred_genres) ? result.profile.preferred_genres : [];
    result.profile.avoided_genres = Array.isArray(result.profile.avoided_genres) ? result.profile.avoided_genres : [];
    result.profile.preferred_languages = Array.isArray(result.profile.preferred_languages) ? result.profile.preferred_languages : [];
    result.profile.avoided_languages = Array.isArray(result.profile.avoided_languages) ? result.profile.avoided_languages : [];
    result.profile.desired_mood = Array.isArray(result.profile.desired_mood) ? result.profile.desired_mood : [];
    result.profile.av_preference = Array.isArray(result.profile.av_preference) ? result.profile.av_preference : [];
    result.profile.favorite_directors = Array.isArray(result.profile.favorite_directors) ? result.profile.favorite_directors : [];
    result.profile.favorite_actors = Array.isArray(result.profile.favorite_actors) ? result.profile.favorite_actors : [];
    result.profile.top_films = Array.isArray(result.profile.top_films) ? result.profile.top_films : [];
    result.profile.feedback_prompted_item_ids = Array.isArray(result.profile.feedback_prompted_item_ids) ? result.profile.feedback_prompted_item_ids : [];
    result.config = result.config || {};
    result.config.saved_views = Array.isArray(result.config.saved_views) ? result.config.saved_views : [];
    result.config.field_options = result.config.field_options && typeof result.config.field_options === "object" ? result.config.field_options : {};
    result.watchlist = result.watchlist || { schema_version: 1, items: [] };
    result.candidatePool = result.candidatePool || { schema_version: 1, items: [] };
    result.history = result.history || { schema_version: 1, events: [] };
    result.recommendLog = result.recommendLog || { schema_version: 1, events: [] };
    result.preferenceEvidence = result.preferenceEvidence || { schema_version: 1, events: [] };
    result.watchlist.items = (result.watchlist.items || []).map(normalizeItem);
    return result;
  }

  function pickNewest(source, draft) {
    if (!draft) return source || {};
    if (!source) return draft;
    const sourceTime = Date.parse(source.exportedAt || "") || 0;
    const draftTime = Date.parse(draft.exportedAt || "") || 0;
    return draftTime > sourceTime ? draft : source;
  }

  function canonicalTitle(value) {
    return String(value || "")
      .normalize("NFKC")
      .toLocaleLowerCase()
      .replace(/[\s·•:：\-—_（）()《》\[\]]+/g, "")
      .trim();
  }

  function importedItems(payload) {
    if (!payload || typeof payload !== "object") return [];
    if (Array.isArray(payload)) return payload;
    if (Array.isArray(payload.items)) return payload.items;
    if (payload.watchlist && Array.isArray(payload.watchlist.items)) return payload.watchlist.items;
    return [];
  }

  function analyzeImport(existingItems, incomingItems) {
    const known = new Map();
    (existingItems || []).forEach(function (item) {
      const key = canonicalTitle(item.title);
      if (key && !known.has(key)) known.set(key, item);
    });
    const newItems = [];
    const duplicates = [];
    const invalid = [];
    (incomingItems || []).forEach(function (item, index) {
      const key = canonicalTitle(item && item.title);
      if (!key) {
        invalid.push({ index: index, reason: "缺少片名", item: item });
        return;
      }
      if (known.has(key)) {
        duplicates.push({ index: index, incoming: item, existing: known.get(key), key: key });
      } else {
        newItems.push(item);
        known.set(key, item);
      }
    });
    return { total: (incomingItems || []).length, newItems: newItems, duplicates: duplicates, invalid: invalid };
  }

  function uniqueId(preferred, used, seed) {
    const base = String(preferred || "import-" + seed).trim() || "import-" + seed;
    let candidate = base;
    let suffix = 2;
    while (used.has(candidate)) {
      candidate = base + "-" + suffix;
      suffix += 1;
    }
    used.add(candidate);
    return candidate;
  }

  function mergeImport(existingItems, incomingItems, policy) {
    const result = clone(existingItems || []).map(normalizeItem);
    const usedIds = new Set(result.map(function (item) { return String(item.id || ""); }).filter(Boolean));
    const stats = { added: 0, skipped: 0, updated: 0, invalid: 0 };
    const mode = ["skip", "keep", "replace"].includes(policy) ? policy : "skip";
    (incomingItems || []).forEach(function (raw, index) {
      const key = canonicalTitle(raw && raw.title);
      if (!key) {
        stats.invalid += 1;
        return;
      }
      const matchIndex = result.findIndex(function (item) { return canonicalTitle(item.title) === key; });
      if (matchIndex >= 0 && mode === "skip") {
        stats.skipped += 1;
        return;
      }
      if (matchIndex >= 0 && mode === "replace") {
        const existingId = result[matchIndex].id;
        result[matchIndex] = normalizeItem(Object.assign({}, result[matchIndex], clone(raw), { id: existingId }), matchIndex);
        stats.updated += 1;
        return;
      }
      const item = normalizeItem(clone(raw), result.length);
      item.id = uniqueId(item.id, usedIds, key + "-" + (index + 1));
      result.push(item);
      stats.added += 1;
    });
    return { items: result, stats: stats };
  }

  function searchable(item) {
    return [item.title, item.title_en, item.director, item.synopsis, item.recommend_reason, item.user_comment]
      .concat(item.genres || [], item.tags || [], item.moods || [])
      .join(" ").toLocaleLowerCase();
  }

  function filterItems(items, filters) {
    filters = filters || {};
    const query = (filters.query || "").trim().toLocaleLowerCase();
    return (items || []).filter(function (item) {
      if (filters.libraryView === "waiting" && !["want", "watching"].includes(item.status)) return false;
      if (filters.libraryView === "favorite" && !item.favorite) return false;
      if (filters.libraryView === "dropped" && item.status !== "dropped") return false;
      if (Array.isArray(filters.statuses) && filters.statuses.length && !filters.statuses.includes(item.status)) return false;
      if (filters.favorite === "yes" && !item.favorite) return false;
      if (filters.favorite === "no" && item.favorite) return false;
      if (filters.planPeriod && periodBucket(item) !== filters.planPeriod) return false;
      if (filters.genreQuery) {
        const genreNeedle = String(filters.genreQuery).trim().toLocaleLowerCase();
        if (genreNeedle && !(item.genres || []).concat(item.tags || []).join(" ").toLocaleLowerCase().includes(genreNeedle)) return false;
      }
      if (filters.yearFrom && Number(item.year || 0) < Number(filters.yearFrom)) return false;
      if (filters.yearTo && Number(item.year || 9999) > Number(filters.yearTo)) return false;
      if (query && !searchable(item).includes(query)) return false;
      if (filters.status && item.status !== filters.status) return false;
      if (filters.contentType && item.content_type !== filters.contentType) return false;
      if (filters.minRating && displayRating(item) < Number(filters.minRating)) return false;
      return true;
    });
  }

  function displayRating(item) {
    const userRating = Number(item && item.user_rating);
    if (Number.isFinite(userRating)) return userRating;
    const workRating = Number(item && item.work_rating);
    if (Number.isFinite(workRating)) return workRating;
    return 0;
  }

  function sortItems(items, sortKey) {
    const sorted = (items || []).slice();
    const text = function (value) { return String(value || "").toLocaleLowerCase(); };
    const number = function (value, fallback) {
      const parsed = Number(value);
      return Number.isFinite(parsed) ? parsed : fallback;
    };
    const strategies = {
      priority_desc: function (a, b) { return number(b.priority, 0) - number(a.priority, 0); },
      added_date_desc: function (a, b) { return text(b.added_date).localeCompare(text(a.added_date)); },
      user_rating_desc: function (a, b) { return number((b.work_rating ?? b.user_rating), -1) - number((a.work_rating ?? a.user_rating), -1); },
      douban_rating_desc: function (a, b) { return number(b.douban_rating, -1) - number(a.douban_rating, -1); },
      year_desc: function (a, b) { return number(b.year, 0) - number(a.year, 0); },
      title_asc: function (a, b) { return text(a.title).localeCompare(text(b.title), "zh-CN"); }
    };
    sorted.sort(strategies[sortKey] || strategies.added_date_desc);
    return sorted;
  }

  function computeStats(items) {
    const watched = (items || []).filter(function (item) { return item.status === "watched"; });
    const ratings = watched.map(function (item) {
      const score = item.work_rating != null ? Number(item.work_rating) : Number(item.user_rating);
      return Number.isFinite(score) ? score : NaN;
    }).filter(Number.isFinite);
    const genreCounts = {};
    const typeCounts = {};
    let minutes = 0;
    watched.forEach(function (item) {
      (item.genres || []).forEach(function (genre) { genreCounts[genre] = (genreCounts[genre] || 0) + 1; });
      typeCounts[item.content_type] = (typeCounts[item.content_type] || 0) + 1;
      minutes += Number(item.duration_min || 0);
    });
    const topGenres = Object.keys(genreCounts).sort(function (a, b) {
      return genreCounts[b] - genreCounts[a] || a.localeCompare(b, "zh-CN");
    }).slice(0, 5).map(function (genre) { return [genre, genreCounts[genre]]; });
    return {
      total: (items || []).length,
      planned: (items || []).filter(function (item) { return item.plan_period && !["watched", "dropped"].includes(item.status); }).length,
      waiting: (items || []).filter(function (item) { return ["want", "watching"].includes(item.status); }).length,
      favorites: (items || []).filter(function (item) { return displayRating(item) >= 9; }).length,
      watched: watched.length,
      averageRating: ratings.length ? Math.round(ratings.reduce(function (a, b) { return a + b; }, 0) / ratings.length * 10) / 10 : null,
      minutes: minutes,
      topGenres: topGenres,
      typeCounts: typeCounts
    };
  }

  function periodBucket(item) {
    const period = String(item.plan_period || "").toLocaleLowerCase();
    if (!period) return "";
    if (period === "week" || period.includes("week") || period.includes("本周")) return "week";
    if (period === "season" || period.includes("season") || period.includes("quarter") || period.includes("本季") || /(^|[-_])q[1-4]($|[-_])/.test(period)) return "season";
    return "month";
  }

  function planGroups(items) {
    const groups = { week: [], month: [], season: [] };
    (items || []).filter(function (item) {
      return item.plan_period && !["watched", "dropped"].includes(item.status);
    }).forEach(function (item) {
      const bucket = periodBucket(item);
      if (bucket) groups[bucket].push(item);
    });
    Object.keys(groups).forEach(function (key) { groups[key] = sortItems(groups[key], "priority_desc"); });
    return groups;
  }

  function profileCompleteness(profile, history, recommendLog) {
    profile = profile || {};
    const has = function (field) {
      const value = profile[field];
      return Array.isArray(value) ? value.length > 0 : Boolean(value);
    };
    const creatorSignals = (profile.favorite_directors || []).length +
      (profile.favorite_actors || []).length + (profile.top_films || []).length;
    const realRatings = (history && history.events || []).filter(function (event) {
      return !event.is_example && event.rating != null;
    }).length;
    const feedback = (recommendLog && recommendLog.events || []).filter(function (event) {
      return !event.is_example && event.feedback;
    }).length;
    const parts = {
      frequency: has("frequency") && profile.frequency !== "irregular" ? 10 : 0,
      genrePreferences: has("preferred_genres") || has("avoided_genres") ? 15 : 0,
      languagePreferences: has("preferred_languages") || has("avoided_languages") ? 8 : 0,
      narrativePace: has("narrative_pace") && profile.narrative_pace !== "mood_dependent" ? 10 : 0,
      desiredMood: has("desired_mood") ? 10 : 0,
      audiovisual: has("av_preference") ? 10 : 0,
      creatorsAndFilms: Math.min(15, creatorSignals * 5),
      ratings: Math.min(20, realRatings * 2),
      recommendationFeedback: Math.min(10, feedback * 2)
    };
    const total = Object.keys(parts).reduce(function (sum, key) { return sum + parts[key]; }, 0);
    return {
      score: Math.min(100, total),
      parts: parts,
      ratingsCount: realRatings,
      feedbackCount: feedback
    };
  }

  function formatDuration(minutes) {
    const value = Number(minutes || 0);
    if (!value) return "时长未知";
    if (value < 60) return value + " 分钟";
    const hours = Math.floor(value / 60);
    const rest = value % 60;
    return rest ? hours + " 小时 " + rest + " 分" : hours + " 小时";
  }

  return {
    STATUS_LABELS: STATUS_LABELS,
    TYPE_LABELS: TYPE_LABELS,
    displayTerm: displayTerm,
    displayTerms: displayTerms,
    decodePayload: decodePayload,
    encodePayload: encodePayload,
    normalize: normalize,
    normalizeItem: normalizeItem,
    pickNewest: pickNewest,
    canonicalTitle: canonicalTitle,
    importedItems: importedItems,
    analyzeImport: analyzeImport,
    mergeImport: mergeImport,
    filterItems: filterItems,
    sortItems: sortItems,
    computeStats: computeStats,
    planGroups: planGroups,
    profileCompleteness: profileCompleteness,
    formatDuration: formatDuration
  };
});
