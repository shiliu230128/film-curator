(function () {
  "use strict";

  const PROJECT_DB_NAME = "film-curator-project-v1";
  const PROJECT_DB_STORE = "handles";
  const Core = window.FilmCore;
  const Sheet = window.FilmSpreadsheet;
  let dataSource = "snapshot";
  let data = Core.normalize(window.FILM_DATA || {});
  let snapshotExportedAt = String(window.FILM_DATA && window.FILM_DATA.exportedAt || "");
  delete data.exportedAt;
  let activeViewId = "all";
  let planPeriod = "week";
  let layout = "grid";
  let selectedId = null;
  let pendingDeleteId = null;
  let pendingImport = null;
  let pendingPosterData = null;
  let editorIsNew = false;
  let editorDuplicateConfirmed = false;
  let toastTimer = null;
  let projectHandle = null;
  let projectHandleName = "";
  let projectDirty = false;
  let projectSaveQueue = Promise.resolve();
  let projectMutationVersion = 0;
  let projectSavedVersion = 0;
  let projectReady = false;

  data.config.saved_views = Array.isArray(data.config.saved_views) ? data.config.saved_views : [];
  data.config.app_name = String(data.config.app_name || "你的观影记录本").trim() || "你的观影记录本";
  const defaultFieldOptions = {
    genres: ["剧情", "喜剧", "爱情", "悬疑", "犯罪", "科幻", "奇幻", "动画", "纪录片", "惊悚", "家庭", "历史", "战争", "音乐"],
    tags: ["高分", "经典", "治愈", "慢燃", "摄影", "女性", "成长", "周末", "下饭"]
  };
  data.config.field_options = data.config.field_options && typeof data.config.field_options === "object" ? data.config.field_options : {};
  Object.keys(defaultFieldOptions).forEach(function (fieldName) {
    if (!Array.isArray(data.config.field_options[fieldName])) {
      const existing = data.watchlist.items.flatMap(function (item) { return item[fieldName] || []; });
      data.config.field_options[fieldName] = Array.from(new Set(defaultFieldOptions[fieldName].concat(existing)));
    }
  });

  const elements = {
    appName: document.getElementById("appName"), editAppName: document.getElementById("editAppNameButton"),
    profileLine: document.getElementById("profileLine"),
    dataSourceStatus: document.getElementById("dataSourceStatus"), exampleStatus: document.getElementById("exampleStatus"),
    clearExamples: document.getElementById("clearExamplesButton"), search: document.getElementById("searchInput"),
    status: document.getElementById("statusFilter"), type: document.getElementById("typeFilter"), period: document.getElementById("periodFilter"),
    rating: document.getElementById("ratingFilter"), sort: document.getElementById("sortSelect"), planList: document.getElementById("planList"),
    libraryGrid: document.getElementById("libraryGrid"), librarySummary: document.getElementById("librarySummary"),
    libraryTabs: document.getElementById("libraryTabs"), insights: document.getElementById("insightsPanel"), audit: document.getElementById("auditPanel"), toast: document.getElementById("toast"),
    theme: document.getElementById("themeToggle"), importInput: document.getElementById("importInput"), detailDialog: document.getElementById("detailDialog"),
    detailTitle: document.getElementById("detailTitle"), dialogKicker: document.getElementById("dialogKicker"), detailView: document.getElementById("detailView"),
    detailActions: document.getElementById("detailActions"), editView: document.getElementById("editView"), editorWarning: document.getElementById("editorDuplicateWarning"),
    deleteDialog: document.getElementById("deleteDialog"), deleteMessage: document.getElementById("deleteMessage"),
    importDialog: document.getElementById("importDialog"), importForm: document.getElementById("importForm"), importSummary: document.getElementById("importSummary"),
    duplicateList: document.getElementById("duplicateList"), exportDialog: document.getElementById("exportDialog"), exportForm: document.getElementById("exportForm"),
    customViewDialog: document.getElementById("customViewDialog"), customViewForm: document.getElementById("customViewForm"),
    nameEditDialog: document.getElementById("nameEditDialog"), nameEditForm: document.getElementById("nameEditForm"),
    completenessDialog: document.getElementById("completenessDialog"), completenessDetails: document.getElementById("completenessDetails"),
    profileEditDialog: document.getElementById("profileEditDialog"), profileEditForm: document.getElementById("profileEditForm"),
    connectProject: document.getElementById("connectProjectButton")
  };

  function openProjectDatabase() {
    return new Promise(function (resolve, reject) {
      if (!window.indexedDB) { resolve(null); return; }
      const request = window.indexedDB.open(PROJECT_DB_NAME, 1);
      request.onupgradeneeded = function () {
        if (!request.result.objectStoreNames.contains(PROJECT_DB_STORE)) {
          request.result.createObjectStore(PROJECT_DB_STORE);
        }
      };
      request.onsuccess = function () { resolve(request.result); };
      request.onerror = function () { reject(request.error || new Error("无法打开本地存储")); };
    });
  }

  async function readProjectHandle() {
    const db = await openProjectDatabase();
    if (!db) return null;
    return new Promise(function (resolve, reject) {
      const transaction = db.transaction(PROJECT_DB_STORE, "readonly");
      const store = transaction.objectStore(PROJECT_DB_STORE);
      const request = store.get("root");
      request.onsuccess = function () { resolve(request.result || null); };
      request.onerror = function () { reject(request.error || new Error("无法读取已保存的项目文件夹")); };
      transaction.oncomplete = function () { db.close(); };
      transaction.onerror = function () { db.close(); reject(transaction.error || new Error("无法读取已保存的项目文件夹")); };
    });
  }

  async function saveProjectHandle(handle) {
    const db = await openProjectDatabase();
    if (!db) return;
    return new Promise(function (resolve, reject) {
      const transaction = db.transaction(PROJECT_DB_STORE, "readwrite");
      const store = transaction.objectStore(PROJECT_DB_STORE);
      store.put(handle, "root");
      transaction.oncomplete = function () { db.close(); resolve(); };
      transaction.onerror = function () { db.close(); reject(transaction.error || new Error("无法保存项目文件夹")); };
    });
  }

  async function clearSavedProjectHandle() {
    const db = await openProjectDatabase();
    if (!db) return;
    return new Promise(function (resolve, reject) {
      const transaction = db.transaction(PROJECT_DB_STORE, "readwrite");
      transaction.objectStore(PROJECT_DB_STORE).delete("root");
      transaction.oncomplete = function () { db.close(); resolve(); };
      transaction.onerror = function () { db.close(); reject(transaction.error || new Error("无法清除项目文件夹")); };
    });
  }

  async function canUseHandle(handle) {
    if (!handle) return false;
    const permission = await handle.queryPermission({ mode: "readwrite" });
    return permission === "granted";
  }

  async function readJsonEntry(directoryHandle, fileName, fallback) {
    try {
      const fileHandle = await directoryHandle.getFileHandle(fileName);
      const file = await fileHandle.getFile();
      return JSON.parse(await file.text());
    } catch (error) {
      if (fallback !== undefined) return fallback;
      throw error;
    }
  }

  async function readProjectData(rootHandle) {
    const dataHandle = await rootHandle.getDirectoryHandle("data");
    const configFallback = Core.decodePayload(window.FILM_DATA && window.FILM_DATA.config || {});
    const snapshotFallback = Core.normalize(window.FILM_DATA || {});
    const payload = {
      profile: await readJsonEntry(dataHandle, "user_profile.json", snapshotFallback.profile || {}),
      watchlist: await readJsonEntry(dataHandle, "watchlist.json", snapshotFallback.watchlist || { schema_version: 1, items: [] }),
      candidatePool: await readJsonEntry(dataHandle, "candidate_pool.json", snapshotFallback.candidatePool || { schema_version: 1, items: [] }),
      history: await readJsonEntry(dataHandle, "history.json", snapshotFallback.history || { schema_version: 1, events: [] }),
      config: await readJsonEntry(dataHandle, "config.json", configFallback || snapshotFallback.config || {}),
      recommendLog: await readJsonEntry(dataHandle, "recommend_log.json", snapshotFallback.recommendLog || { schema_version: 1, events: [] }),
      preferenceEvidence: await readJsonEntry(dataHandle, "preference_evidence.json", snapshotFallback.preferenceEvidence || { schema_version: 1, events: [] })
    };
    return Core.normalize(payload);
  }

  async function writeTextFile(directoryHandle, fileName, content) {
    const fileHandle = await directoryHandle.getFileHandle(fileName, { create: true });
    const writable = await fileHandle.createWritable();
    await writable.write(content);
    await writable.close();
  }

  function dataLanguage() {
    return data && data.config && data.config.field_language ? data.config.field_language : "zh";
  }

  async function writeProjectData(rootHandle, sourceData) {
    const dataHandle = await rootHandle.getDirectoryHandle("data", { create: true });
    const webHandle = await rootHandle.getDirectoryHandle("web", { create: true });
    const language = sourceData && sourceData.config && sourceData.config.field_language ? sourceData.config.field_language : "zh";
    await writeTextFile(dataHandle, "user_profile.json", JSON.stringify(Core.encodePayload(sourceData.profile || {}, language), null, 2) + "\n");
    await writeTextFile(dataHandle, "watchlist.json", JSON.stringify(Core.encodePayload(sourceData.watchlist || { schema_version: 1, items: [] }, language), null, 2) + "\n");
    await writeTextFile(dataHandle, "candidate_pool.json", JSON.stringify(Core.encodePayload(sourceData.candidatePool || { schema_version: 1, items: [] }, language), null, 2) + "\n");
    await writeTextFile(dataHandle, "history.json", JSON.stringify(Core.encodePayload(sourceData.history || { schema_version: 1, events: [] }, language), null, 2) + "\n");
    await writeTextFile(dataHandle, "config.json", JSON.stringify(Core.encodePayload(sourceData.config || {}, language), null, 2) + "\n");
    await writeTextFile(dataHandle, "recommend_log.json", JSON.stringify(Core.encodePayload(sourceData.recommendLog || { schema_version: 1, events: [] }, language), null, 2) + "\n");
    await writeTextFile(dataHandle, "preference_evidence.json", JSON.stringify(Core.encodePayload(sourceData.preferenceEvidence || { schema_version: 1, events: [] }, language), null, 2) + "\n");
    const snapshotPayload = Object.assign({}, JSON.parse(JSON.stringify(sourceData)), { exportedAt: new Date().toISOString() });
    await writeTextFile(webHandle, "data.js", "window.FILM_DATA = " + JSON.stringify(Core.encodePayload(snapshotPayload, language), null, 2) + ";\n");
  }

  function refreshConnectionStatus() {
    const label = projectHandle ? (projectHandleName || projectHandle.name || "项目文件夹") : "未连接项目文件夹";
    const sourceLabel = projectHandle ? "当前数据：项目主数据" : "当前数据：网页快照";
    const dirtyLabel = projectDirty ? "（有未同步改动）" : "";
    elements.dataSourceStatus.textContent = sourceLabel + " · " + label + dirtyLabel;
    if (elements.connectProject) {
      elements.connectProject.textContent = projectHandle ? "重新连接项目文件夹" : "连接项目文件夹";
    }
  }

  function markProjectDirty(message) {
    projectMutationVersion += 1;
    projectDirty = true;
    refreshConnectionStatus();
    if (message) {
      if (projectHandle) showToast(message + "，已标记为同步中");
      else showToast(message + "，先连接项目文件夹才能写回主数据");
    }
  }

  function persist(message) {
    markProjectDirty(message);
    if (projectHandle) {
      queueProjectFlush().catch(function () {});
    }
  }

  async function flushProjectData() {
    if (!projectHandle || !projectDirty) return;
    const version = projectMutationVersion;
    const snapshot = Core.normalize(JSON.parse(JSON.stringify(data)));
    delete snapshot.exportedAt;
    try {
      await writeProjectData(projectHandle, snapshot);
      projectSavedVersion = version;
      if (projectSavedVersion === projectMutationVersion) {
        projectDirty = false;
        dataSource = "project";
        window.FILM_DATA = Object.assign({}, Core.encodePayload(Object.assign({}, snapshot, { exportedAt: new Date().toISOString() }), dataLanguage()));
      }
      refreshConnectionStatus();
    } catch (error) {
      showToast("写回项目文件失败：" + error.message);
      throw error;
    }
  }

  function queueProjectFlush() {
    if (!projectHandle) return Promise.resolve();
    projectSaveQueue = projectSaveQueue.then(function () {
      return flushProjectData();
    }).catch(function () { return null; });
    return projectSaveQueue;
  }

  async function connectProjectFolder() {
    if (!window.showDirectoryPicker) {
      showToast("这个浏览器不支持连接项目文件夹");
      return;
    }
    try {
      const handle = await window.showDirectoryPicker({ mode: "readwrite" });
      await handle.getDirectoryHandle("data");
      await handle.getDirectoryHandle("web");
      const granted = await handle.requestPermission({ mode: "readwrite" });
      if (granted !== "granted") {
        showToast("没有拿到写入权限，暂时不能连接");
        return;
      }
      projectHandle = handle;
      projectHandleName = handle.name || "项目文件夹";
      await saveProjectHandle(handle);
      data = await readProjectData(handle);
      delete data.exportedAt;
      dataSource = "project";
      projectDirty = false;
      snapshotExportedAt = String(window.FILM_DATA && window.FILM_DATA.exportedAt || snapshotExportedAt);
      refreshConnectionStatus();
      render();
      showToast("已连接项目文件夹：" + projectHandleName);
    } catch (error) {
      if (error && error.name === "AbortError") return;
      showToast("连接失败：" + error.message);
    }
  }

  async function restoreProjectFolder() {
    try {
      const handle = await readProjectHandle();
      if (!handle) { refreshConnectionStatus(); return; }
      const granted = await canUseHandle(handle);
      if (!granted) {
        await clearSavedProjectHandle();
        refreshConnectionStatus();
        return;
      }
      projectHandle = handle;
      projectHandleName = handle.name || "项目文件夹";
      data = await readProjectData(handle);
      delete data.exportedAt;
      dataSource = "project";
      projectDirty = false;
      refreshConnectionStatus();
      render();
    } catch (error) {
      refreshConnectionStatus();
    }
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>'"]/g, function (character) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[character];
    });
  }

  function splitCsv(value) {
    return String(value || "").split(/[,，、;；|]/).map(function (part) { return part.trim(); }).filter(Boolean);
  }

  function localId(title) {
    const base = Core.canonicalTitle(title) || "film";
    const used = new Set(data.watchlist.items.map(function (item) { return item.id; }));
    let candidate = "local-" + base + "-" + Date.now();
    let suffix = 2;
    while (used.has(candidate)) { candidate = "local-" + base + "-" + Date.now() + "-" + suffix; suffix += 1; }
    return candidate;
  }

  function posterMarkup(item, className) {
    if (!item.poster_url) return "";
    return '<img class="film-thumb ' + (className || "") + '" src="' + escapeHtml(item.poster_url) + '" alt="' + escapeHtml(item.title) + ' 图片" loading="lazy" onerror="this.remove()">';
  }

  function tagMarkup(item) {
    return (item.genres || []).concat(item.tags || []).slice(0, 5).map(function (tag) { return '<span class="tag">' + escapeHtml(Core.displayTerm(tag)) + "</span>"; }).join("");
  }

  function ratingMarkup(item) {
    const douban = item.douban_rating == null ? "暂无" : Number(item.douban_rating).toFixed(1);
    const mine = item.user_rating == null ? "未评分" : Number(item.user_rating).toFixed(1);
    const work = item.work_rating == null ? "未填写" : Number(item.work_rating).toFixed(1);
    const fit = item.fit_rating == null ? "未填写" : Number(item.fit_rating).toFixed(1);
    return '<div class="rating-pair"><span>作品评价 <b>' + escapeHtml(work) + '</b></span><span>我的评分 <b>' + escapeHtml(mine) + '</b></span><span>豆瓣 <b>' + escapeHtml(douban) + '</b></span><span class="quiet-metric">适配度（可选） <b>' + escapeHtml(fit) + '</b></span></div>';
  }

  function planCardMarkup(item) {
    return '<article class="plan-card' + (item.poster_url ? " has-thumb" : "") + '" data-id="' + escapeHtml(item.id) + '" tabindex="0" role="button" aria-label="打开 ' + escapeHtml(item.title) + ' 详情">' + posterMarkup(item, "plan-thumb") + '<div class="plan-card-body"><div class="card-topline"><span class="status-pill">' + escapeHtml(Core.STATUS_LABELS[item.status]) + '</span></div><h3>' + escapeHtml(item.title) + '</h3><p class="film-meta">' + escapeHtml(compactMeta(item)) + '</p><p class="recommend-reason"><span>推荐理由</span>' + escapeHtml(item.recommend_reason || "点击补充推荐理由") + '</p><div class="tag-row">' + tagMarkup(item) + "</div></div></article>";
  }

  function recordCardMarkup(item) {
    const exampleTag = item.is_example ? '<span class="tag example-tag">示例</span>' : "";
    return '<article class="record-card' + (item.poster_url ? " has-thumb" : "") + '" data-id="' + escapeHtml(item.id) + '" tabindex="0" role="button" aria-label="打开 ' + escapeHtml(item.title) + ' 详情">' + posterMarkup(item) + '<div class="record-body"><div class="card-topline"><span class="status-pill">' + escapeHtml(Core.STATUS_LABELS[item.status]) + '</span>' + exampleTag + '</div><h3>' + escapeHtml(item.title) + '</h3><p class="film-meta">' + escapeHtml(compactMeta(item)) + '</p><div class="tag-row">' + tagMarkup(item) + '</div>' + ratingMarkup(item) + '</div></article>';
  }

  function periodValue(raw) {
    const period = String(raw || "").toLocaleLowerCase();
    if (!period) return "";
    if (period === "week" || period.includes("week") || period.includes("本周")) return "week";
    if (period === "season" || period.includes("season") || period.includes("quarter") || period.includes("本季") || /(^|[-_])q[1-4]($|[-_])/.test(period)) return "season";
    return "month";
  }

  function compactMeta(item) {
    return [item.year, Core.TYPE_LABELS[item.content_type] || item.content_type, item.director, item.duration_min ? Core.formatDuration(item.duration_min) : "", item.country_region].filter(Boolean).join(" · ");
  }

  function defaultViewFilters(id) {
    return { all: {}, waiting: { statuses: ["want", "watching"] }, favorite: { minRating: "9" }, dropped: { statuses: ["dropped"] } }[id] || {};
  }

  function activeViewFilters() {
    const custom = data.config.saved_views.find(function (view) { return view.id === activeViewId; });
    return custom ? custom.filters || {} : defaultViewFilters(activeViewId);
  }

  function currentFilters() {
    const base = activeViewFilters();
    return {
      query: elements.search.value,
      statuses: elements.status.value ? [elements.status.value] : (base.statuses || []),
      contentType: elements.type.value || base.contentType || "",
      planPeriod: elements.period.value || base.planPeriod || "",
      minRating: elements.rating.value || base.minRating || "",
      favorite: base.favorite || "",
      genreQuery: base.genreQuery || ""
    };
  }

  function renderStats() {
    const items = data.watchlist.items;
    elements.profileLine.textContent = "看世界，见自己";
    const examples = items.filter(function (item) { return item.is_example; }).length;
    refreshConnectionStatus();
    elements.exampleStatus.textContent = "示例记录 " + examples + " 条";
    elements.clearExamples.hidden = examples === 0;
    renderInsights();
  }

  function renderInsights() {
    const stats = Core.computeStats(data.watchlist.items.filter(function (item) { return !item.is_example; }));
    const maxGenre = stats.topGenres.length ? stats.topGenres[0][1] : 1;
    const genreRows = stats.topGenres.length ? stats.topGenres.map(function (entry) { return '<div class="bar-row"><span>' + escapeHtml(entry[0]) + '</span><span class="bar-track"><span style="width:' + Math.round(entry[1] / maxGenre * 100) + '%"></span></span><b>' + entry[1] + "</b></div>"; }).join("") : '<p class="insight-note">示例记录不会计入正式统计。录入真实观影后，这里会出现类型分布。</p>';
    const typeLabels = Object.keys(stats.typeCounts || {}).sort(function (a, b) { return stats.typeCounts[b] - stats.typeCounts[a] || a.localeCompare(b, "zh-CN"); });
    const typeRows = typeLabels.length ? typeLabels.map(function (type) { return '<span class="tag">' + escapeHtml(Core.displayTerm(Core.TYPE_LABELS[type] || type)) + ' ' + stats.typeCounts[type] + '</span>'; }).join("") : '<span class="choice-empty">暂无真实完成记录</span>';
    const profile = data.profile || {};
    const profileBits = [
      (profile.preferred_genres || []).length ? "偏好：" + Core.displayTerms(profile.preferred_genres).slice(0, 4).join("、") : "偏好类型待补充",
      (profile.preferred_languages || []).length ? "语言：" + Core.displayTerms(profile.preferred_languages).slice(0, 3).join("、") : "",
      profile.subtitle_mode && profile.subtitle_mode !== "any" ? "字幕场景：" + Core.displayTerm(profile.subtitle_mode) : ""
    ].filter(Boolean).join(" · ");
    elements.insights.innerHTML = '<article class="insight-card"><h3>内容类型与题材</h3><div class="tag-row">' + typeRows + '</div>' + genreRows + '</article><article class="insight-card"><h3>累计时长</h3><strong class="insight-number">' + Math.round(stats.minutes / 60) + '</strong><p>小时 · ' + stats.watched + ' 部真实完成记录</p></article><article class="insight-card"><h3>画像摘要</h3><p class="insight-copy">' + escapeHtml(profileBits || "还没有真实画像；先记录几部看过的，再让 AI 问几个轻量问题。") + '</p><p class="insight-copy">默认“最爱清单”显示 9 分以上作品，已弃视图显示状态为已弃的记录。</p></article>';
    renderAudit();
  }

  function renderAudit() {
    const profile = data.profile || {};
    const hasRealProfile = !profile.is_example;
    const evidence = (data.preferenceEvidence && data.preferenceEvidence.events || []).filter(function (event) { return !event.is_example; });
    const prompted = new Set((profile.feedback_prompted_item_ids || []).map(String));
    const pending = (data.history.events || []).filter(function (event) { return !event.is_example && event.item_id && !prompted.has(String(event.item_id)); });
    const preferenceText = hasRealProfile ? [
      (profile.preferred_genres || []).length ? "偏好 " + profile.preferred_genres.join("、") : "偏好类型还不明确",
      (profile.avoided_genres || []).length ? "避开 " + profile.avoided_genres.join("、") : "暂无长期禁区",
      profile.narrative_pace ? "节奏 " + profile.narrative_pace : ""
    ].filter(Boolean).join(" · ") : "尚未建立真实画像；当前示例偏好不会用于正式推荐。";
    const evidenceRows = evidence.slice(-3).reverse().map(function (event) { return '<li><strong>' + escapeHtml(event.signal) + '</strong><span>' + escapeHtml(event.reason || event.source || "对话记录") + (event.confirmed ? " · 已确认" : " · 待校准") + '</span></li>'; }).join("");
    const pendingRows = pending.slice(0, 3).map(function (event) { return '<li><strong>' + escapeHtml(event.title || "未命名作品") + '</strong><span>可在下次对话自然询问一次观看感受</span></li>'; }).join("");
    elements.audit.innerHTML = '<div class="audit-heading"><div><span class="section-kicker">画像与反馈</span><h3>系统目前怎样理解你</h3></div><button class="quiet-button" id="editProfileButton" type="button">修正画像</button></div><p class="audit-summary">' + escapeHtml(preferenceText) + '</p><div class="audit-columns"><div><h4>偏好依据</h4><ul>' + (evidenceRows || '<li><span>还没有真实偏好证据。示例数据不计入。</span></li>') + '</ul></div><div><h4>待跟进反馈</h4><ul>' + (pendingRows || '<li><span>没有需要追问的真实观看记录。</span></li>') + '</ul></div></div>';
  }

  function renderPlan() {
    const groups = Core.planGroups(data.watchlist.items);
    const items = groups[planPeriod] || [];
    document.getElementById("planCount").textContent = groups.week.length + groups.month.length + groups.season.length + " 部";
    elements.planList.innerHTML = items.length ? items.map(planCardMarkup).join("") : '<div class="empty-state"><strong>这个周期还没有安排</strong><span>新增一条计划，或从记录详情中选择计划周期。</span></div>';
  }

  function renderViewTabs() {
    const all = data.watchlist.items;
    const counts = {
      all: all.length,
      waiting: Core.filterItems(all, defaultViewFilters("waiting")).length,
      favorite: Core.filterItems(all, defaultViewFilters("favorite")).length,
      dropped: Core.filterItems(all, defaultViewFilters("dropped")).length
    };
    const defaults = [["all", "全部"], ["waiting", "待看"], ["favorite", "最爱清单"], ["dropped", "已弃"]];
    elements.libraryTabs.innerHTML = defaults.map(function (view) { const active = view[0] === activeViewId; return '<button class="' + (active ? "active" : "") + '" type="button" data-library-view="' + view[0] + '" role="tab" aria-selected="' + active + '">' + view[1] + ' <span>' + counts[view[0]] + "</span></button>"; }).join("") + data.config.saved_views.map(function (view) { const active = view.id === activeViewId; const count = Core.filterItems(all, view.filters || {}).length; return '<span class="custom-tab-wrap"><button class="custom-tab ' + (active ? "active" : "") + '" type="button" data-library-view="' + escapeHtml(view.id) + '" role="tab" aria-selected="' + active + '">' + escapeHtml(view.name) + " <span>" + count + '</span></button><button class="delete-view-button" type="button" data-delete-view="' + escapeHtml(view.id) + '" aria-label="删除视图 ' + escapeHtml(view.name) + '" title="删除此筛选视图">×</button></span>'; }).join("") + '<button class="new-view-button" id="newViewButton" type="button">＋ 新建视图</button>';
  }

  function renderLibrary() {
    const items = Core.sortItems(Core.filterItems(data.watchlist.items, currentFilters()), elements.sort.value);
    renderViewTabs();
    elements.libraryGrid.className = "record-grid " + layout + "-view";
    elements.libraryGrid.innerHTML = items.length ? items.map(recordCardMarkup).join("") : '<div class="empty-state"><strong>没有找到符合条件的记录</strong><span>换个关键词，或清空筛选条件。</span></div>';
    const viewName = activeViewId === "all" ? "全部" : activeViewId === "waiting" ? "待看" : activeViewId === "favorite" ? "最爱清单" : activeViewId === "dropped" ? "已弃" : (data.config.saved_views.find(function (view) { return view.id === activeViewId; }) || {}).name;
    elements.librarySummary.textContent = "“" + (viewName || "当前") + "”视图显示 " + items.length + " 条 · 视图只是筛选，不会复制记录";
  }

  function render() { renderStats(); renderPlan(); renderLibrary(); }

  async function refreshProjectData() {
    if (!projectHandle || projectDirty) return;
    try {
      const next = await readProjectData(projectHandle);
      const nextSignature = JSON.stringify(next);
      const currentSignature = JSON.stringify(data);
      if (nextSignature !== currentSignature) {
        data = next;
        delete data.exportedAt;
        dataSource = "project";
        render();
      }
    } catch (error) {
      if (error && error.name !== "NotAllowedError") showToast("重新读取项目文件失败：" + error.message);
    }
  }

  function refreshSnapshot() {
    return new Promise(function (resolve) {
      const script = document.createElement("script");
      const cacheBuster = Date.now();
      script.src = "data.js?v=" + cacheBuster;
      script.onload = function () {
        const nextExportedAt = String(window.FILM_DATA && window.FILM_DATA.exportedAt || "");
        if (nextExportedAt && nextExportedAt !== snapshotExportedAt) {
          snapshotExportedAt = nextExportedAt;
          data = Core.normalize(window.FILM_DATA || {});
          delete data.exportedAt;
          dataSource = "snapshot";
          render();
          if (!projectHandle) showToast("主数据已更新，网页已同步");
        }
        script.remove();
        resolve();
      };
      script.onerror = function () {
        script.remove();
        resolve();
      };
      document.head.appendChild(script);
    });
  }

  function refreshCurrentData() {
    if (projectHandle) return refreshProjectData();
    return refreshSnapshot();
  }

  function showToast(message) {
    elements.toast.textContent = message; elements.toast.classList.add("visible"); clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { elements.toast.classList.remove("visible"); }, 3000);
  }

  function openDialog(dialog) { if (!dialog.open) dialog.showModal(); }
  function closeDialog(dialog) { if (dialog && dialog.open) dialog.close(); }
  function findItem(id) { return data.watchlist.items.find(function (item) { return item.id === id; }); }

  function editableField(label, field, value, display) {
    return '<button class="editable-field" type="button" data-inline-field="' + field + '"><span>' + label + '：</span><b>' + escapeHtml(display == null || display === "" ? "未填写" : display) + '</b></button>';
  }

  function choiceValueMarkup(values) {
    return values.length ? values.map(function (value) { return '<span class="choice-chip">' + escapeHtml(Core.displayTerm(value)) + "</span>"; }).join("") : '<span class="choice-empty">未选择</span>';
  }

  function choiceFieldMarkup(label, field, selectedValues) {
    const selected = Array.isArray(selectedValues) ? selectedValues : [];
    const options = Array.from(new Set((data.config.field_options[field] || []).concat(selected)));
    const rows = options.length ? options.map(function (option) {
      const checked = selected.includes(option) ? " checked" : "";
      const display = Core.displayTerm(option);
      return '<div class="choice-option"><label><input type="checkbox" data-choice-toggle data-choice-field="' + field + '" value="' + escapeHtml(option) + '"' + checked + '><span>' + escapeHtml(display) + '</span></label><button class="choice-delete" type="button" data-choice-delete data-choice-field="' + field + '" data-choice-value="' + escapeHtml(option) + '" title="删除选项" aria-label="删除选项 ' + escapeHtml(display) + '">🗑</button></div>';
    }).join("") : '<p class="choice-empty-row">还没有候选项</p>';
    return '<details class="choice-editor" data-choice-field="' + field + '"><summary><span class="choice-label">' + label + '：</span><span class="choice-summary-content">' + choiceValueMarkup(selected) + '</span></summary><div class="choice-menu">' + rows + '<button class="choice-add" type="button" data-choice-add data-choice-field="' + field + '">＋ 新增选项</button></div></details>';
  }

  function detailMarkup(item) {
    const plan = { week: "本周", month: "本月", season: "本季" }[periodValue(item.plan_period)] || "未加入计划";
    const mine = item.user_rating == null ? "未评分" : Number(item.user_rating).toFixed(1) + " / 10";
    const work = item.work_rating == null ? "未填写" : Number(item.work_rating).toFixed(1) + " / 10";
    const fit = item.fit_rating == null ? "未填写" : Number(item.fit_rating).toFixed(1) + " / 10";
    const tags = Core.displayTerms(item.tags || []).join("、");
    const genres = Core.displayTerms(item.genres || []).join("、");
    const fixedMeta = [item.year, Core.TYPE_LABELS[item.content_type] || item.content_type, item.director, item.duration_min ? Core.formatDuration(item.duration_min) : "", item.douban_rating == null ? "" : "豆瓣 " + Number(item.douban_rating).toFixed(1), item.country_region, item.language].filter(Boolean).join(" · ");
    return '<div class="detail-summary">' + posterMarkup(item, "detail-thumb") + '<div class="detail-summary-copy"><p class="detail-subtitle">' + escapeHtml(item.title_en || "") + '</p><p class="compact-meta">' + escapeHtml(fixedMeta || "基础信息未填写") + '</p><button class="meta-edit-button" type="button" data-detail-action="edit">修改基础信息</button><div class="detail-status">' + (item.is_example ? '<span class="tag example-tag">示例</span>' : "") + '</div></div></div><div class="editable-grid">' + editableField("状态", "status", item.status, Core.STATUS_LABELS[item.status]) + editableField("计划周期", "plan_period", item.plan_period, plan) + editableField("我的评分", "user_rating", item.user_rating, mine) + editableField("作品评价", "work_rating", item.work_rating, work) + choiceFieldMarkup("影片类型", "genres", item.genres) + choiceFieldMarkup("自定义标签", "tags", item.tags) + editableField("简介", "synopsis", item.synopsis, item.synopsis) + editableField("为什么推荐", "recommend_reason", item.recommend_reason, item.recommend_reason) + editableField("我的短评", "user_comment", item.user_comment, item.user_comment) + '<div class="quiet-note">适配度（可选）：' + escapeHtml(fit) + '</div></div>';
  }

  function openDetail(id) {
    const item = findItem(id); if (!item) return;
    selectedId = id; editorIsNew = false; elements.detailTitle.textContent = item.title; elements.dialogKicker.textContent = "影片记录";
    elements.detailView.innerHTML = detailMarkup(item); elements.detailView.hidden = false; elements.editView.hidden = true; elements.detailActions.hidden = false;
    elements.detailActions.innerHTML = '<button class="danger-button" type="button" data-detail-action="delete">删除这条记录</button>';
    openDialog(elements.detailDialog);
  }

  function inlineControl(field, item) {
    if (field === "status") return '<select name="value">' + Object.keys(Core.STATUS_LABELS).map(function (key) { return '<option value="' + key + '"' + (item.status === key ? " selected" : "") + '>' + Core.STATUS_LABELS[key] + "</option>"; }).join("") + "</select>";
    if (field === "plan_period") return '<select name="value"><option value="">不加入计划</option>' + [["week", "本周"], ["month", "本月"], ["season", "本季"]].map(function (entry) { return '<option value="' + entry[0] + '"' + (periodValue(item.plan_period) === entry[0] ? " selected" : "") + '>' + entry[1] + "</option>"; }).join("") + "</select>";
    if (field === "favorite") return '<label class="inline-check"><input name="value" type="checkbox"' + (item.favorite ? " checked" : "") + "><span>加入最爱清单</span></label>";
    if (["user_rating", "work_rating", "fit_rating"].includes(field)) return '<input name="value" type="number" min="0" max="10" step="0.5" value="' + escapeHtml(item[field] == null ? "" : item[field]) + '" placeholder="0-10">';
    if (["genres", "tags"].includes(field)) return '<input name="value" value="' + escapeHtml((item[field] || []).join("、")) + '" placeholder="用顿号分隔">';
    return '<textarea name="value" rows="4">' + escapeHtml(item[field] || "") + "</textarea>";
  }

  function startInlineEdit(field, button) {
    const item = findItem(selectedId); if (!item) return;
    const label = button.querySelector("span").textContent;
    button.outerHTML = '<form class="inline-edit-form" data-inline-form="' + field + '"><label>' + escapeHtml(label) + '</label>' + inlineControl(field, item) + '</form>';
    const form = elements.detailView.querySelector('form[data-inline-form="' + field + '"]');
    if (form) {
      const input = form.elements.value;
      input.focus();
      if (input.select && input.type !== "number") input.select();
    }
  }

  function saveInline(form) {
    if (!form || !form.isConnected || form.dataset.saved === "true") return;
    form.dataset.saved = "true";
    const item = findItem(selectedId); if (!item) return;
    const field = form.dataset.inlineForm;
    const input = form.elements.value;
    let value = input.type === "checkbox" ? input.checked : input.value;
    if (["genres", "tags"].includes(field)) value = splitCsv(value);
    if (["user_rating", "work_rating", "fit_rating"].includes(field)) value = value === "" ? null : Number(value);
    item[field] = value;
    if (field === "plan_period") item.plan_period = value;
    persist("已更新“" + elements.detailTitle.textContent + "”的" + form.querySelector("label").textContent);
    render(); openDetail(selectedId);
  }

  function choiceFieldLabel(fieldName) {
    return fieldName === "genres" ? "影片类型" : "自定义标签";
  }

  function updateChoiceSelection(input) {
    const fieldName = input.dataset.choiceField;
    if (!["genres", "tags"].includes(fieldName)) return;
    const item = findItem(selectedId); if (!item) return;
    const values = new Set(item[fieldName] || []);
    if (input.checked) values.add(input.value); else values.delete(input.value);
    item[fieldName] = Array.from(values);
    persist("已更新“" + item.title + "”的" + choiceFieldLabel(fieldName));
    render();
    const details = input.closest(".choice-editor");
    if (details) details.querySelector(".choice-summary-content").innerHTML = choiceValueMarkup(item[fieldName]);
  }

  function startChoiceAdd(button) {
    const fieldName = button.dataset.choiceField;
    button.outerHTML = '<form class="choice-add-form" data-choice-add-form="' + fieldName + '"><input name="option_name" required maxlength="24" autocomplete="off" placeholder="输入新选项，按回车添加"><button type="submit">添加</button></form>';
    const form = elements.detailView.querySelector('form[data-choice-add-form="' + fieldName + '"]');
    if (form) form.elements.option_name.focus();
  }

  function addChoiceOption(form) {
    const fieldName = form.dataset.choiceAddForm;
    if (!["genres", "tags"].includes(fieldName)) return;
    const value = form.elements.option_name.value.trim();
    if (!value) return;
    const options = data.config.field_options[fieldName];
    if (!options.some(function (option) { return option.toLocaleLowerCase() === value.toLocaleLowerCase(); })) options.push(value);
    const item = findItem(selectedId);
    if (item && !(item[fieldName] || []).includes(value)) item[fieldName] = (item[fieldName] || []).concat(value);
    persist("已新增" + choiceFieldLabel(fieldName) + "选项“" + value + "”");
    render(); openDetail(selectedId);
  }

  function deleteChoiceOption(button) {
    const fieldName = button.dataset.choiceField;
    const value = button.dataset.choiceValue;
    if (!["genres", "tags"].includes(fieldName) || !value) return;
    if (!window.confirm("删除选项“" + value + "”？它会从全部记录的" + choiceFieldLabel(fieldName) + "中移除。")) return;
    data.config.field_options[fieldName] = data.config.field_options[fieldName].filter(function (option) { return option !== value; });
    data.watchlist.items.forEach(function (item) { item[fieldName] = (item[fieldName] || []).filter(function (option) { return option !== value; }); });
    persist("已删除" + choiceFieldLabel(fieldName) + "选项“" + value + "”");
    render(); openDetail(selectedId);
  }

  function field(form, name) { return form.elements[name]; }

  function fillForm(item, isNew, period) {
    const form = elements.editView;
    const value = function (name, fallback) { const current = item && item[name]; return current == null ? (fallback == null ? "" : fallback) : current; };
    field(form, "id").value = isNew ? "" : value("id", "");
    ["title", "title_en", "year", "director", "duration_min", "country_region", "language", "episode_count", "watch_episodes", "watch_duration_min", "release_date", "douban_rating", "user_rating", "work_rating", "fit_rating", "priority", "synopsis", "recommend_reason", "user_comment"].forEach(function (name) { field(form, name).value = value(name, ""); });
    field(form, "actors").value = (item && item.actors || []).join("、"); field(form, "genres").value = (item && item.genres || []).join("、"); field(form, "tags").value = (item && item.tags || []).join("、");
    field(form, "favorite").checked = Boolean(item && item.favorite); field(form, "status").value = value("status", "want"); field(form, "plan_period").value = periodValue(period || value("plan_period", "")); field(form, "poster_file").value = "";
  }

  function startEdit(item) {
    if (!item) return; editorIsNew = false; editorDuplicateConfirmed = false; pendingPosterData = null;
    elements.detailTitle.textContent = "编辑基础信息"; elements.dialogKicker.textContent = item.title; fillForm(item, false);
    elements.editView.querySelectorAll(".record-field").forEach(function (label) { label.hidden = true; });
    elements.detailView.hidden = true; elements.detailActions.hidden = true; elements.editView.hidden = false; elements.editorWarning.hidden = true;
  }

  function startCreate(period) {
    selectedId = null; editorIsNew = true; editorDuplicateConfirmed = false; pendingPosterData = null;
    elements.detailTitle.textContent = "新增影片记录"; elements.dialogKicker.textContent = "添加一条记录"; fillForm({ status: "want", plan_period: period || "" }, true, period || "");
    elements.editView.querySelectorAll(".record-field").forEach(function (label) { label.hidden = false; });
    elements.detailView.hidden = true; elements.detailActions.hidden = true; elements.editView.hidden = false; elements.editorWarning.hidden = true; openDialog(elements.detailDialog);
  }

  function backToDetail() { if (selectedId) openDetail(selectedId); else closeDialog(elements.detailDialog); }

  function formItem() {
    const form = elements.editView; const id = field(form, "id").value.trim(); const existing = findItem(id) || {};
    return Core.normalizeItem({
      id: id || localId(field(form, "title").value), title: field(form, "title").value.trim(), title_en: field(form, "title_en").value.trim(),
      year: field(form, "year").value ? Number(field(form, "year").value) : null, director: field(form, "director").value.trim(),
      actors: splitCsv(field(form, "actors").value), country_region: field(form, "country_region").value.trim(), language: field(form, "language").value.trim(),
      content_type: field(form, "content_type").value, duration_min: field(form, "duration_min").value ? Number(field(form, "duration_min").value) : null,
      episode_count: field(form, "episode_count").value ? Number(field(form, "episode_count").value) : null, watch_episodes: field(form, "watch_episodes").value ? Number(field(form, "watch_episodes").value) : null, watch_duration_min: field(form, "watch_duration_min").value ? Number(field(form, "watch_duration_min").value) : null, release_date: field(form, "release_date").value,
      douban_rating: field(form, "douban_rating").value ? Number(field(form, "douban_rating").value) : null, user_rating: field(form, "user_rating").value ? Number(field(form, "user_rating").value) : null, work_rating: field(form, "work_rating").value ? Number(field(form, "work_rating").value) : null, fit_rating: field(form, "fit_rating").value ? Number(field(form, "fit_rating").value) : null,
      status: field(form, "status").value, plan_period: field(form, "plan_period").value, favorite: field(form, "favorite").checked,
      priority: field(form, "priority").value ? Number(field(form, "priority").value) : 0, genres: splitCsv(field(form, "genres").value), tags: splitCsv(field(form, "tags").value),
      synopsis: field(form, "synopsis").value.trim(), recommend_reason: field(form, "recommend_reason").value.trim(), user_comment: field(form, "user_comment").value.trim(),
      poster_url: pendingPosterData || existing.poster_url || "", source: existing.source || "manual", moods: existing.moods || [],
      added_date: editorIsNew ? new Date().toISOString().slice(0, 10) : existing.added_date, watched_date: existing.watched_date || null
    });
  }

  function saveForm(event) {
    event.preventDefault(); const item = formItem(); if (!item.title) return;
    const duplicate = data.watchlist.items.find(function (candidate) { return candidate.id !== item.id && Core.canonicalTitle(candidate.title) === Core.canonicalTitle(item.title); });
    if (duplicate && !editorDuplicateConfirmed) { elements.editorWarning.textContent = "发现同名记录：“" + duplicate.title + "”。再次保存可并存，或先检查年份。"; elements.editorWarning.hidden = false; editorDuplicateConfirmed = true; return; }
    if (editorIsNew) data.watchlist.items.push(item); else { const index = data.watchlist.items.findIndex(function (candidate) { return candidate.id === item.id; }); if (index >= 0) data.watchlist.items[index] = Object.assign({}, data.watchlist.items[index], item); }
    persist(editorIsNew ? "已新增记录" : "已保存基础信息"); closeDialog(elements.detailDialog); render();
  }

  function resizePoster(file) {
    if (!file || !file.type.startsWith("image/")) return Promise.reject(new Error("请选择图片文件"));
    return new Promise(function (resolve, reject) {
      const reader = new FileReader();
      reader.onload = function () {
        const image = new Image();
        image.onload = function () {
          const scale = Math.min(1, 640 / image.width, 800 / image.height); const canvas = document.createElement("canvas");
          canvas.width = Math.max(1, Math.round(image.width * scale)); canvas.height = Math.max(1, Math.round(image.height * scale));
          canvas.getContext("2d").drawImage(image, 0, 0, canvas.width, canvas.height); resolve(canvas.toDataURL("image/jpeg", 0.82));
        };
        image.onerror = function () { reject(new Error("图片无法读取")); }; image.src = reader.result;
      };
      reader.onerror = function () { reject(new Error("图片无法读取")); }; reader.readAsDataURL(file);
    });
  }

  function requestDelete(id) {
    const item = findItem(id); if (!item) return; pendingDeleteId = id;
    elements.deleteMessage.textContent = "将删除“" + item.title + "”这条当前记录；历史观影和推荐日志不会被连带删除。"; openDialog(elements.deleteDialog);
  }

  function confirmDelete() {
    if (!pendingDeleteId) return; data.watchlist.items = data.watchlist.items.filter(function (item) { return item.id !== pendingDeleteId; }); persist("已删除记录");
    closeDialog(elements.deleteDialog); closeDialog(elements.detailDialog); pendingDeleteId = null; render();
  }

  async function previewImport(file) {
    try {
      let incoming;
      if (String(file.name).toLocaleLowerCase().endsWith(".json")) incoming = Core.importedItems(JSON.parse(await file.text()));
      else incoming = await Sheet.readFile(file);
      if (!incoming || !incoming.length) throw new Error("没有读取到带片名的记录");
      incoming = incoming.map(function (item, index) { return Core.normalizeItem(item, index); });
      const analysis = Core.analyzeImport(data.watchlist.items, incoming); pendingImport = { incoming: incoming, analysis: analysis };
      elements.importSummary.textContent = "从 " + file.name + " 读取 " + analysis.total + " 条：新增 " + analysis.newItems.length + " 条，名称重复 " + analysis.duplicates.length + " 条，无效 " + analysis.invalid.length + " 条。导入只会新增或更新记录，不会覆盖整个数据库。";
      elements.duplicateList.innerHTML = analysis.duplicates.length ? '<p class="duplicate-heading">重复名称</p>' + analysis.duplicates.map(function (entry) { return '<div class="duplicate-row"><strong>' + escapeHtml(entry.incoming.title) + '</strong><span>已有：' + escapeHtml(entry.existing.title) + (entry.existing.year ? "（" + entry.existing.year + "）" : "") + "</span></div>"; }).join("") : '<p class="empty-inline">没有检测到重名。</p>';
      openDialog(elements.importDialog);
    } catch (error) { showToast("导入失败：" + error.message); }
  }

  function applyImport(event) {
    event.preventDefault(); if (!pendingImport) return;
    const merged = Core.mergeImport(data.watchlist.items, pendingImport.incoming, elements.importForm.elements.duplicatePolicy.value); data.watchlist.items = merged.items;
    persist("已导入 " + merged.stats.added + " 条新记录" + (merged.stats.skipped ? "，跳过 " + merged.stats.skipped + " 条重名" : "")); closeDialog(elements.importDialog); pendingImport = null; render();
  }

  function downloadBlob(blob, fileName) {
    const link = document.createElement("a"); link.href = URL.createObjectURL(blob); link.download = fileName; document.body.appendChild(link); link.click(); link.remove();
    setTimeout(function () { URL.revokeObjectURL(link.href); }, 1000);
  }

  async function exportData(event) {
    event.preventDefault(); const format = elements.exportForm.elements.exportFormat.value;
    try {
      if (format === "json") downloadBlob(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }), "film-curator-backup.json");
      else if (format === "csv") downloadBlob(new Blob([Sheet.toCsv(data.watchlist.items)], { type: "text/csv;charset=utf-8" }), Sheet.fileNameFor("csv"));
      else downloadBlob(await Sheet.toXlsx(data.watchlist.items), Sheet.fileNameFor("xlsx"));
      closeDialog(elements.exportDialog); showToast("已导出 " + format.toUpperCase() + " 文件");
    } catch (error) { showToast("导出失败：" + error.message); }
  }

  function openCustomViewDialog() {
    elements.customViewForm.reset();
    const filters = currentFilters();
    elements.customViewForm.elements.view_status.value = (filters.statuses || []).length === 1 ? filters.statuses[0] : "";
    elements.customViewForm.elements.view_type.value = filters.contentType || "";
    elements.customViewForm.elements.view_period.value = filters.planPeriod || "";
    elements.customViewForm.elements.view_rating.value = filters.minRating || "";
    elements.customViewForm.elements.view_favorite.value = filters.favorite || "";
    elements.customViewForm.elements.view_genre.value = filters.genreQuery || "";
    openDialog(elements.customViewDialog);
  }

  function applyViewFiltersToControls(viewId) {
    const filters = activeViewFilters();
    elements.status.value = (filters.statuses || []).length === 1 ? filters.statuses[0] : "";
    elements.type.value = filters.contentType || "";
    elements.period.value = filters.planPeriod || "";
    elements.rating.value = filters.minRating || "";
  }

  function openNameEditDialog() {
    elements.nameEditForm.elements.app_name.value = data.config.app_name;
    openDialog(elements.nameEditDialog);
    elements.nameEditForm.elements.app_name.focus();
  }

  function saveName(event) {
    event.preventDefault();
    const name = elements.nameEditForm.elements.app_name.value.trim();
    if (!name) return;
    data.config.app_name = name;
    elements.appName.textContent = name;
    persist("已更新记录本名称");
    closeDialog(elements.nameEditDialog);
  }

  function openProfileEdit() {
    const form = elements.profileEditForm;
    form.elements.preferred_genres.value = (data.profile.preferred_genres || []).join("、");
    form.elements.avoided_genres.value = (data.profile.avoided_genres || []).join("、");
    form.elements.preferred_languages.value = (data.profile.preferred_languages || []).join("、");
    form.elements.avoided_languages.value = (data.profile.avoided_languages || []).join("、");
    form.elements.subtitle_mode.value = data.profile.subtitle_mode || "any";
    form.elements.narrative_pace.value = data.profile.narrative_pace || "";
    form.elements.desired_mood.value = (data.profile.desired_mood || []).join("、");
    openDialog(elements.profileEditDialog);
  }

  function saveProfileEdit(event) {
    event.preventDefault();
    const form = elements.profileEditForm;
    data.profile.preferred_genres = splitCsv(form.elements.preferred_genres.value);
    data.profile.avoided_genres = splitCsv(form.elements.avoided_genres.value);
    data.profile.preferred_languages = splitCsv(form.elements.preferred_languages.value);
    data.profile.avoided_languages = splitCsv(form.elements.avoided_languages.value);
    data.profile.subtitle_mode = form.elements.subtitle_mode.value;
    data.profile.narrative_pace = form.elements.narrative_pace.value.trim();
    data.profile.desired_mood = splitCsv(form.elements.desired_mood.value);
    data.profile.is_example = false;
    data.profile.last_updated = new Date().toISOString().slice(0, 10);
    data.preferenceEvidence.events.push({ id: "local-profile-" + Date.now(), signal: "用户修正长期画像", source: "web_profile_audit", reason: "用户在网页审计入口明确修改", confirmed: true, date: data.profile.last_updated });
    persist("已修正长期画像"); closeDialog(elements.profileEditDialog); render();
  }

  function saveCustomView(event) {
    event.preventDefault(); const form = elements.customViewForm; const name = form.elements.view_name.value.trim(); if (!name) return;
    const id = "view-" + Date.now();
    data.config.saved_views.push({ id: id, name: name, filters: { statuses: form.elements.view_status.value ? [form.elements.view_status.value] : [], contentType: form.elements.view_type.value, planPeriod: form.elements.view_period.value, favorite: form.elements.view_favorite.value, minRating: form.elements.view_rating.value, genreQuery: form.elements.view_genre.value.trim() } });
    activeViewId = id; persist("已保存筛选视图“" + name + "”"); closeDialog(elements.customViewDialog); renderLibrary();
  }

  function deleteCustomView(id) {
    const view = data.config.saved_views.find(function (entry) { return entry.id === id; }); if (!view) return;
    data.config.saved_views = data.config.saved_views.filter(function (entry) { return entry.id !== id; }); activeViewId = "all"; persist("已删除筛选视图"); renderLibrary();
  }

  function renderCompleteness() {
    const result = Core.profileCompleteness(data.profile, data.history, data.recommendLog);
    const labels = { frequency: "观影频率", genrePreferences: "喜欢/避开的类型", languagePreferences: "语言偏好", narrativePace: "叙事节奏", desiredMood: "想要的情绪", audiovisual: "视听偏好", creatorsAndFilms: "喜欢的导演、演员或影片", ratings: "真实观影评分", recommendationFeedback: "推荐反馈" };
    elements.completenessDetails.innerHTML = '<div class="formula-total"><strong>' + result.score + '%</strong><span>当前画像完整度</span></div>' + Object.keys(result.parts).map(function (key) { return '<div class="formula-row"><span>' + labels[key] + '</span><b>' + result.parts[key] + '</b></div>'; }).join("") + '<p class="formula-note">上限 100 分。评分每部 +2 分，最多 20 分；推荐反馈每次 +2 分，最多 10 分。</p>';
  }

  function populateFilters() {
    const statusOptions = '<option value="">全部状态</option>' + Object.keys(Core.STATUS_LABELS).map(function (key) { return '<option value="' + key + '">' + Core.STATUS_LABELS[key] + "</option>"; }).join("");
    const typeOptions = '<option value="">全部类型</option>' + Object.keys(Core.TYPE_LABELS).map(function (key) { return '<option value="' + key + '">' + Core.TYPE_LABELS[key] + "</option>"; }).join("");
    elements.status.innerHTML = statusOptions; elements.type.innerHTML = typeOptions;
    elements.editView.elements.content_type.innerHTML = typeOptions.replace('<option value="">全部类型</option>', "");
    elements.editView.elements.status.innerHTML = statusOptions.replace('<option value="">全部状态</option>', "");
    elements.customViewForm.elements.view_status.innerHTML = statusOptions; elements.customViewForm.elements.view_type.innerHTML = typeOptions;
  }

  function bindEvents() {
    [elements.search, elements.status, elements.type, elements.period, elements.rating, elements.sort].forEach(function (input) { input.addEventListener("input", renderLibrary); input.addEventListener("change", renderLibrary); });
    document.addEventListener("click", function (event) {
      const activeInline = document.activeElement && document.activeElement.closest ? document.activeElement.closest(".inline-edit-form") : null;
      if (activeInline && !activeInline.contains(event.target)) saveInline(activeInline);
      const target = event.target.closest("button, article"); if (!target) return;
      if (target.dataset.closeDialog) { closeDialog(document.getElementById(target.dataset.closeDialog)); return; }
      if (target.dataset.deleteView) { deleteCustomView(target.dataset.deleteView); return; }
      if (target.dataset.planPeriod) { planPeriod = target.dataset.planPeriod; document.querySelectorAll("[data-plan-period]").forEach(function (button) { const active = button.dataset.planPeriod === planPeriod; button.classList.toggle("active", active); button.setAttribute("aria-selected", String(active)); }); renderPlan(); return; }
      if (target.dataset.libraryView) { activeViewId = target.dataset.libraryView; applyViewFiltersToControls(activeViewId); renderLibrary(); return; }
      if (target.id === "newViewButton") { openCustomViewDialog(); return; }
      if (target.dataset.view) { layout = target.dataset.view; document.querySelectorAll("[data-view]").forEach(function (button) { button.classList.toggle("active", button.dataset.view === layout); }); renderLibrary(); return; }
      if (target.dataset.createPeriod) { startCreate(target.dataset.createPeriod); return; }
      if (target.id === "createRecordButton") { startCreate(""); return; }
      if (target.id === "editAppNameButton") { openNameEditDialog(); return; }
      if (target.dataset.choiceDelete !== undefined) { deleteChoiceOption(target); return; }
      if (target.dataset.choiceAdd !== undefined) { startChoiceAdd(target); return; }
      if (target.id === "importButton") { elements.importInput.click(); return; }
      if (target.id === "exportButton") { openDialog(elements.exportDialog); return; }
      if (target.id === "connectProjectButton") { connectProjectFolder(); return; }
      if (target.id === "dataInfoButton") { openDialog(document.getElementById("dataInfoDialog")); return; }
      if (target.id === "completenessButton") { renderCompleteness(); openDialog(elements.completenessDialog); return; }
      if (target.id === "editProfileButton") { openProfileEdit(); return; }
      if (target.id === "clearExamplesButton") { if (window.confirm("确定清除全部示例记录吗？")) { data.watchlist.items = data.watchlist.items.filter(function (item) { return !item.is_example; }); persist("已清除示例记录"); render(); } return; }
      if (target.dataset.detailAction === "edit") { startEdit(findItem(selectedId)); return; }
      if (target.dataset.detailAction === "delete") { requestDelete(selectedId); return; }
      if (target.dataset.inlineField) { startInlineEdit(target.dataset.inlineField, target); return; }
      if (target.dataset.cancelEdit !== undefined) { backToDetail(); return; }
      if (target.id === "confirmDeleteButton") { confirmDelete(); return; }
      if (target.dataset.id && (target.classList.contains("record-card") || target.classList.contains("plan-card"))) openDetail(target.dataset.id);
    });
    document.addEventListener("focusout", function (event) {
      const form = event.target.closest(".inline-edit-form");
      if (!form) return;
      setTimeout(function () {
        if (form.isConnected && !form.contains(document.activeElement)) saveInline(form);
      }, 0);
    });
    document.addEventListener("change", function (event) {
      if (event.target.dataset.choiceToggle !== undefined) { updateChoiceSelection(event.target); return; }
      const form = event.target.closest(".inline-edit-form");
      if (form && event.target.name === "value" && event.target.tagName === "SELECT") saveInline(form);
    });
    document.addEventListener("submit", function (event) {
      const inlineForm = event.target.closest(".inline-edit-form");
      if (inlineForm) { event.preventDefault(); saveInline(inlineForm); return; }
      const choiceForm = event.target.closest(".choice-add-form");
      if (choiceForm) { event.preventDefault(); addChoiceOption(choiceForm); }
    });
    document.addEventListener("keydown", function (event) { if (event.key === "Enter" && event.target.matches("article[data-id]")) openDetail(event.target.dataset.id); });
    elements.editView.addEventListener("submit", saveForm);
    elements.editView.elements.poster_file.addEventListener("change", async function () { if (!this.files[0]) return; try { pendingPosterData = await resizePoster(this.files[0]); showToast("图片已准备好，保存记录后生效"); } catch (error) { showToast(error.message); } });
    elements.importInput.addEventListener("change", function () { if (this.files[0]) previewImport(this.files[0]); this.value = ""; });
    elements.importForm.addEventListener("submit", applyImport); elements.exportForm.addEventListener("submit", exportData); elements.customViewForm.addEventListener("submit", saveCustomView); elements.nameEditForm.addEventListener("submit", saveName); elements.profileEditForm.addEventListener("submit", saveProfileEdit);
    elements.theme.addEventListener("click", function () { const next = document.documentElement.dataset.theme === "fresh-light" ? "fresh-dark" : "fresh-light"; document.documentElement.dataset.theme = next; elements.theme.textContent = next === "fresh-light" ? "◐" : "☼"; });
    window.addEventListener("focus", refreshCurrentData);
    setInterval(refreshCurrentData, 30000);
  }

  elements.appName.textContent = data.config.app_name;
  populateFilters(); bindEvents(); render();
  refreshConnectionStatus();
  restoreProjectFolder();
})();
