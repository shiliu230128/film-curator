(function (root, factory) {
  const api = factory(root.JSZip);
  if (typeof module === "object" && module.exports) module.exports = api;
  root.FilmSpreadsheet = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function (JSZip) {
  "use strict";

  const COLUMNS = [
    ["id", "记录 ID"], ["title", "片名"], ["title_en", "英文名"], ["year", "年份"], ["director", "导演"],
    ["actors", "主演"], ["country_region", "国家/地区"], ["language", "语言"], ["genres", "类型"],
    ["content_type", "内容类型"], ["duration_min", "时长（分钟）"], ["episode_count", "集数"],
    ["release_date", "上映日期"], ["douban_rating", "豆瓣评分"], ["user_rating", "我的评分"],
    ["work_rating", "作品评价"], ["fit_rating", "当时适配度"],
    ["status", "状态"], ["favorite", "最爱"], ["plan_period", "计划周期"], ["priority", "优先级"],
    ["tags", "自定义标签"], ["moods", "情绪"], ["synopsis", "简介"], ["recommend_reason", "推荐理由"],
    ["user_comment", "我的短评"], ["poster_url", "图片地址"], ["source", "来源"], ["added_date", "加入日期"],
    ["watched_date", "看完日期"]
  ];
  const KEYS = COLUMNS.map(function (column) { return column[0]; });
  const LABELS = COLUMNS.map(function (column) { return column[1]; });
  const ALIASES = {
    "记录id": "id", "id": "id", "片名": "title", "title": "title", "英文名": "title_en", "title_en": "title_en",
    "年份": "year", "year": "year", "导演": "director", "director": "director", "主演": "actors", "actors": "actors",
    "国家/地区": "country_region", "国家地区": "country_region", "country_region": "country_region", "语言": "language", "language": "language",
    "类型": "genres", "类型标签": "genres", "genres": "genres", "内容类型": "content_type", "content_type": "content_type",
    "时长（分钟）": "duration_min", "时长分钟": "duration_min", "duration_min": "duration_min", "集数": "episode_count", "episode_count": "episode_count",
    "上映日期": "release_date", "release_date": "release_date", "豆瓣评分": "douban_rating", "douban_rating": "douban_rating",
    "我的评分": "user_rating", "user_rating": "user_rating", "作品评价": "work_rating", "work_rating": "work_rating",
    "当时适配度": "fit_rating", "fit_rating": "fit_rating", "状态": "status", "status": "status", "最爱": "favorite", "favorite": "favorite",
    "计划周期": "plan_period", "plan_period": "plan_period", "优先级": "priority", "priority": "priority", "自定义标签": "tags", "标签": "tags", "tags": "tags",
    "情绪": "moods", "moods": "moods", "简介": "synopsis", "synopsis": "synopsis", "推荐理由": "recommend_reason", "recommend_reason": "recommend_reason",
    "我的短评": "user_comment", "user_comment": "user_comment", "图片地址": "poster_url", "poster_url": "poster_url", "来源": "source", "source": "source",
    "加入日期": "added_date", "added_date": "added_date", "看完日期": "watched_date", "watched_date": "watched_date"
  };

  function escapeXml(value) {
    return String(value == null ? "" : value).replace(/[<>&'\"]/g, function (character) {
      return { "<": "&lt;", ">": "&gt;", "&": "&amp;", "'": "&apos;", '"': "&quot;" }[character];
    });
  }

  function unescapeXml(value) {
    return String(value || "").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
      .replace(/&quot;/g, '"').replace(/&apos;/g, "'").replace(/&amp;/g, "&");
  }

  function csvEscape(value) {
    const text = String(value == null ? "" : value);
    return /[",\r\n]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
  }

  function stringifyValue(key, value) {
    if (Array.isArray(value)) return value.join("、");
    if (key === "favorite") return value ? "是" : "否";
    return value == null ? "" : value;
  }

  function toRows(items) {
    return [LABELS].concat((items || []).map(function (item) {
      return KEYS.map(function (key) { return stringifyValue(key, item[key]); });
    }));
  }

  function toCsv(items) {
    return "\ufeff" + toRows(items).map(function (row) { return row.map(csvEscape).join(","); }).join("\r\n") + "\r\n";
  }

  function parseCsv(text, delimiter) {
    const input = String(text || "").replace(/^\ufeff/, "");
    const separator = delimiter || (input.split(/\r?\n/, 1)[0].split("\t").length > input.split(/\r?\n/, 1)[0].split(",").length ? "\t" : ",");
    const rows = [];
    let row = [];
    let cell = "";
    let quoted = false;
    for (let index = 0; index < input.length; index += 1) {
      const character = input[index];
      if (quoted) {
        if (character === '"' && input[index + 1] === '"') { cell += '"'; index += 1; }
        else if (character === '"') quoted = false;
        else cell += character;
      } else if (character === '"' && cell === "") quoted = true;
      else if (character === separator) { row.push(cell); cell = ""; }
      else if (character === "\n") { row.push(cell.replace(/\r$/, "")); rows.push(row); row = []; cell = ""; }
      else cell += character;
    }
    if (cell || row.length) { row.push(cell.replace(/\r$/, "")); rows.push(row); }
    return rows.filter(function (current) { return current.some(function (value) { return String(value).trim() !== ""; }); });
  }

  function normalizeKey(value) {
    return String(value || "").normalize("NFKC").trim().toLocaleLowerCase();
  }

  function parseCellValue(key, raw) {
    const value = String(raw == null ? "" : raw).trim();
    if (!value) return key === "favorite" ? false : (key === "genres" || key === "tags" || key === "moods" || key === "actors" ? [] : null);
    if (["genres", "tags", "moods", "actors"].includes(key)) return value.split(/[,，、;；|]/).map(function (part) { return part.trim(); }).filter(Boolean);
    if (key === "favorite") return ["是", "true", "1", "yes", "y"].includes(value.toLocaleLowerCase());
    if (["year", "duration_min", "episode_count", "priority"].includes(key)) return Number(value) || null;
    if (["douban_rating", "user_rating", "work_rating", "fit_rating"].includes(key)) return Number(value) || null;
    return value;
  }

  function rowsToItems(rows) {
    if (!rows || rows.length < 2) return [];
    const header = rows[0].map(function (value) { return ALIASES[normalizeKey(value)] || normalizeKey(value); });
    return rows.slice(1).map(function (row, rowIndex) {
      const item = { id: "sheet-row-" + (rowIndex + 2), title: "" };
      header.forEach(function (key, columnIndex) {
        if (KEYS.includes(key)) item[key] = parseCellValue(key, row[columnIndex]);
      });
      return item;
    }).filter(function (item) { return item.title; });
  }

  function columnName(index) {
    let result = "";
    let value = index + 1;
    while (value) { const remainder = (value - 1) % 26; result = String.fromCharCode(65 + remainder) + result; value = Math.floor((value - 1) / 26); }
    return result;
  }

  function xlsxXml(items) {
    const rows = toRows(items).map(function (row, rowIndex) {
      const cells = row.map(function (value, columnIndex) {
        const text = String(value == null ? "" : value);
        const ref = columnName(columnIndex) + (rowIndex + 1);
        if (rowIndex === 0) return '<c r="' + ref + '" t="inlineStr" s="1"><is><t>' + escapeXml(text) + "</t></is></c>";
        if (["年份", "时长（分钟）", "集数", "豆瓣评分", "我的评分", "作品评价", "当时适配度", "优先级"].includes(LABELS[columnIndex]) && text !== "" && Number.isFinite(Number(text))) return '<c r="' + ref + '"><v>' + Number(text) + "</v></c>";
        return '<c r="' + ref + '" t="inlineStr"><is><t xml:space="preserve">' + escapeXml(text) + "</t></is></c>";
      }).join("");
      return '<row r="' + (rowIndex + 1) + '">' + cells + "</row>";
    }).join("");
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><sheetFormatPr defaultRowHeight="20"/><cols>' + LABELS.map(function (_, index) { return '<col min="' + (index + 1) + '" max="' + (index + 1) + '" width="' + (index === 1 ? 24 : 16) + '" customWidth="1"/>'; }).join("") + "</cols><sheetData>" + rows + "</sheetData><autoFilter ref=\"A1:" + columnName(LABELS.length - 1) + (toRows(items).length) + '\"/></worksheet>';
  }

  async function toXlsx(items) {
    if (!JSZip) throw new Error("XLSX 需要加载本地表格组件");
    const zip = new JSZip();
    zip.file("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>');
    zip.file("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>');
    zip.file("xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="影视记录" sheetId="1" r:id="rId1"/></sheets></workbook>');
    zip.file("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>');
    zip.file("xl/styles.xml", '<?xml version="1.0" encoding="UTF-8"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><numFmts count="0"/><fonts count="2"><font><sz val="11"/><name val="Aptos"/></font><font><b/><sz val="11"/><name val="Aptos"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="solid"><fgColor rgb="DCEFE8"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/><xf numFmtId="0" fontId="1" fillId="1" borderId="0" applyFont="1" applyFill="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>');
    zip.file("xl/worksheets/sheet1.xml", xlsxXml(items));
    return zip.generateAsync({ type: "blob", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
  }

  async function fromXlsx(arrayBuffer) {
    if (!JSZip) throw new Error("XLSX 需要加载本地表格组件");
    const zip = await JSZip.loadAsync(arrayBuffer);
    const sheetFile = zip.file("xl/worksheets/sheet1.xml");
    if (!sheetFile) throw new Error("XLSX 中没有可读取的第一张工作表");
    const xml = await sheetFile.async("text");
    const sharedFile = zip.file("xl/sharedStrings.xml");
    let sharedStrings = [];
    if (sharedFile) {
      const sharedXml = await sharedFile.async("text");
      const sharedDoc = new DOMParser().parseFromString(sharedXml, "application/xml");
      sharedStrings = Array.from(sharedDoc.getElementsByTagNameNS("http://schemas.openxmlformats.org/spreadsheetml/2006/main", "si")).map(function (entry) {
        return Array.from(entry.getElementsByTagNameNS("http://schemas.openxmlformats.org/spreadsheetml/2006/main", "t")).map(function (node) { return node.textContent; }).join("");
      });
    }
    const doc = new DOMParser().parseFromString(xml, "application/xml");
    if (doc.querySelector("parsererror")) throw new Error("XLSX 工作表无法解析");
    const rows = Array.from(doc.getElementsByTagNameNS("http://schemas.openxmlformats.org/spreadsheetml/2006/main", "row")).map(function (row) {
      const cells = {};
      Array.from(row.getElementsByTagNameNS("http://schemas.openxmlformats.org/spreadsheetml/2006/main", "c")).forEach(function (cell) {
        const ref = cell.getAttribute("r") || "A1";
        const letters = ref.replace(/\d+/g, "");
        let column = 0;
        for (let index = 0; index < letters.length; index += 1) column = column * 26 + letters.charCodeAt(index) - 64;
        column -= 1;
        const textNode = cell.getElementsByTagNameNS("http://schemas.openxmlformats.org/spreadsheetml/2006/main", "t")[0];
        const valueNode = cell.getElementsByTagNameNS("http://schemas.openxmlformats.org/spreadsheetml/2006/main", "v")[0];
        const rawValue = textNode ? textNode.textContent : (valueNode ? valueNode.textContent : "");
        cells[column] = cell.getAttribute("t") === "s" ? (sharedStrings[Number(rawValue)] || "") : rawValue;
      });
      const max = Object.keys(cells).reduce(function (value, key) { return Math.max(value, Number(key)); }, -1);
      return Array.from({ length: max + 1 }, function (_, index) { return unescapeXml(cells[index] || ""); });
    });
    return rowsToItems(rows);
  }

  async function readFile(file) {
    const name = String(file.name || "").toLocaleLowerCase();
    if (name.endsWith(".csv") || name.endsWith(".tsv")) return rowsToItems(parseCsv(await file.text(), name.endsWith(".tsv") ? "\t" : undefined));
    if (name.endsWith(".xlsx") || name.endsWith(".xlsm")) return fromXlsx(await file.arrayBuffer());
    return null;
  }

  function fileNameFor(format) {
    return format === "csv" ? "film-curator-records.csv" : "film-curator-records.xlsx";
  }

  return { COLUMNS: COLUMNS, toRows: toRows, toCsv: toCsv, parseCsv: parseCsv, rowsToItems: rowsToItems, toXlsx: toXlsx, fromXlsx: fromXlsx, readFile: readFile, fileNameFor: fileNameFor };
});
