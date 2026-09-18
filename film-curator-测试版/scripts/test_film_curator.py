"""字段中文化的读写边界测试。只用标准库，跑法：python3 scripts/test_film_curator.py"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import film_curator as fc


def write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class TranslationTest(unittest.TestCase):
    def test_round_trip_keeps_data(self) -> None:
        internal = {
            "schema_version": 1,
            "items": [{
                "id": "it_1", "title": "四月物语", "content_type": "movie",
                "status": "watched", "plan_period": "week", "favorite": True,
                "work_rating": 8.5, "fit_rating": 7, "genres": ["剧情", "爱情"],
                "added_date": "2026-08-01", "is_example": False,
            }],
        }
        encoded = fc.encode_payload(internal, "zh")
        self.assertEqual(encoded["记录"][0]["状态"], "已看")
        self.assertEqual(encoded["记录"][0]["内容类型"], "电影")
        self.assertEqual(encoded["记录"][0]["计划周期"], "本周")
        self.assertEqual(encoded["记录"][0]["最爱"], True)
        self.assertEqual(fc.decode_payload(encoded), internal)

    def test_encode_and_decode_are_idempotent(self) -> None:
        internal = {"items": [{"id": "it_1", "status": "want", "content_type": "series"}]}
        once = fc.encode_payload(internal, "zh")
        self.assertEqual(fc.encode_payload(once, "zh"), once)
        self.assertEqual(fc.decode_payload(fc.decode_payload(once)), internal)

    def test_english_and_mixed_files_still_read(self) -> None:
        mixed = {"记录": [{"id": "it_1", "状态": "watched", "content_type": "电影"}]}
        decoded = fc.decode_payload(mixed)
        self.assertEqual(decoded["items"][0]["status"], "watched")
        self.assertEqual(decoded["items"][0]["content_type"], "movie")

    def test_legacy_status_aliases(self) -> None:
        pairs = {"planned": "want", "paused": "want", "想看": "want",
                 "看完": "watched", "弃看": "dropped", "在看": "watching"}
        for stored, expected in pairs.items():
            decoded = fc.decode_payload({"items": [{"status": stored}]})
            self.assertEqual(decoded["items"][0]["status"], expected, stored)

    def test_unknown_keys_pass_through(self) -> None:
        payload = {"items": [{"id": "it_1", "my_own_note": "留着", "嵌套": {"随手写的": 1}}]}
        encoded = fc.encode_payload(payload, "zh")
        self.assertEqual(encoded["记录"][0]["my_own_note"], "留着")
        self.assertEqual(encoded["记录"][0]["嵌套"], {"随手写的": 1})
        self.assertEqual(fc.decode_payload(encoded), payload)

    def test_genre_weights_keys_are_user_data(self) -> None:
        internal = {"genre_weights": {"剧情": 3, "语言": 2, "状态": 1, "id": 5}}
        encoded = fc.encode_payload(internal, "zh")
        self.assertEqual(encoded["类型权重"], internal["genre_weights"])
        self.assertEqual(fc.decode_payload(encoded), internal)

    def test_field_options_values_are_user_data(self) -> None:
        internal = {"field_options": {"genres": ["剧情", "悬疑"], "tags": ["状态", "语言"]}}
        encoded = fc.encode_payload(internal, "zh")
        self.assertEqual(encoded["候选项"]["类型"], ["剧情", "悬疑"])
        self.assertEqual(encoded["候选项"]["自定义标签"], ["状态", "语言"])
        self.assertEqual(fc.decode_payload(encoded), internal)

    def test_saved_view_filters_keep_their_own_names(self) -> None:
        internal = {"saved_views": [{
            "id": "v1", "name": "本周待看",
            "filters": {"statuses": ["want"], "contentType": "movie", "planPeriod": "week"},
        }]}
        encoded = fc.encode_payload(internal, "zh")
        view = encoded["自定义视图"][0]
        self.assertEqual(view["视图ID"], "v1")
        self.assertEqual(view["视图名称"], "本周待看")
        self.assertEqual(view["筛选条件"]["状态列表"], ["待看"])
        self.assertEqual(view["筛选条件"]["内容类型筛选"], "电影")
        self.assertEqual(fc.decode_payload(encoded), internal)

    def test_english_target_writes_english(self) -> None:
        chinese = {"记录": [{"记录ID": "it_1", "状态": "已看", "内容类型": "纪录片"}]}
        english = fc.encode_payload(chinese, "en")
        self.assertEqual(english, {"items": [{"id": "it_1", "status": "watched",
                                              "content_type": "documentary"}]})

    def test_chinese_names_are_unique(self) -> None:
        seen: dict[str, str] = {}
        for internal, chinese in fc.FIELD_NAMES.items():
            self.assertNotIn(chinese, seen, f"{chinese} 同时是 {seen.get(chinese)} 和 {internal}")
            seen[chinese] = internal


class SetAssignmentTest(unittest.TestCase):
    def test_chinese_and_english_assignments_match(self) -> None:
        chinese = fc.parse_assignments(["状态=已看", "我的评分=8.5", "计划周期=本月"])
        english = fc.parse_assignments(["status=watched", "work_rating=8.5", "plan_period=month"])
        self.assertEqual(chinese, english)
        self.assertEqual(chinese["status"], "watched")

    def test_legacy_rating_names_map_to_work_rating(self) -> None:
        """旧文件写「我的评分」(user_rating)、中间版本写「作品评价」，都读进 work_rating。"""
        for legacy in ("user_rating=8.5", "作品评价=8.5"):
            self.assertEqual(fc.parse_assignments([legacy]), {"work_rating": 8.5})

    def test_unknown_field_is_rejected_with_hint(self) -> None:
        """写错字段名要当场报错。之前会静默新建一个没人读的键，数据看着正常其实丢了。"""
        with self.assertRaises(fc.FilmCuratorError) as caught:
            fc.parse_assignments(["duration=163"], fc.ITEM_WRITABLE_FIELDS)
        message = str(caught.exception)
        self.assertIn("duration", message)
        self.assertIn("时长分钟", message)

    def test_list_fields_split_on_common_separators(self) -> None:
        """类型这种列表字段用逗号写也要拆开，否则存成一整串文字，筛选会漏掉这条。"""
        parsed = fc.parse_assignments(["类型=剧情,动作、爱情；战争"], fc.ITEM_WRITABLE_FIELDS)
        self.assertEqual(parsed["genres"], ["剧情", "动作", "爱情", "战争"])
        explicit = fc.parse_assignments(['类型=["纪录","历史"]'], fc.ITEM_WRITABLE_FIELDS)
        self.assertEqual(explicit["genres"], ["纪录", "历史"])


class DataDirTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name) / "data"
        fc.FIELD_LANGUAGE_OVERRIDE = None
        fc._FIELD_LANGUAGE_CACHE.clear()
        fc.ACTIVE_DATA_DIR = self.data_dir

    def tearDown(self) -> None:
        fc.FIELD_LANGUAGE_OVERRIDE = None
        fc._FIELD_LANGUAGE_CACHE.clear()
        fc.ACTIVE_DATA_DIR = fc.DEFAULT_DATA_DIR
        self.tmp.cleanup()

    def run_cli(self, *argv: str) -> int:
        return fc.main(["--data-dir", str(self.data_dir), *argv])

    def test_init_writes_chinese_files(self) -> None:
        self.assertEqual(self.run_cli("init"), 0)
        raw = json.loads((self.data_dir / "watchlist.json").read_text(encoding="utf-8"))
        self.assertIn("结构版本", raw)
        self.assertIn("记录", raw)
        config = json.loads((self.data_dir / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(config["字段语言"], "zh")

    def test_add_then_read_back(self) -> None:
        self.run_cli("init")
        self.assertEqual(self.run_cli("add", "--title", "测试片", "--status", "已看"), 0)
        raw = json.loads((self.data_dir / "watchlist.json").read_text(encoding="utf-8"))
        added = [item for item in raw["记录"] if item["片名"] == "测试片"]
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0]["状态"], "已看")
        items = fc.read_json(self.data_dir / "watchlist.json")["items"]
        self.assertTrue(any(item["status"] == "watched" for item in items))

    def test_english_status_flag_still_accepted(self) -> None:
        self.run_cli("init")
        self.assertEqual(self.run_cli("add", "--title", "英文入参", "--status", "watched"), 0)
        raw = json.loads((self.data_dir / "watchlist.json").read_text(encoding="utf-8"))
        added = [item for item in raw["记录"] if item["片名"] == "英文入参"]
        self.assertEqual(added[0]["状态"], "已看")

    def test_migrate_from_english_files(self) -> None:
        write(self.data_dir / "watchlist.json", {
            "schema_version": 1,
            "items": [{"id": "it_1", "title": "老数据", "content_type": "movie",
                       "status": "planned", "added_date": "2026-01-01"}],
        })
        summary = fc.migrate_fields(self.data_dir, "zh", apply_changes=False)
        self.assertFalse(summary["applied"])
        raw = json.loads((self.data_dir / "watchlist.json").read_text(encoding="utf-8"))
        self.assertIn("items", raw, "预演不该改文件")

        applied = fc.migrate_fields(self.data_dir, "zh", apply_changes=True)
        self.assertTrue(applied["applied"])
        self.assertEqual(applied["validation_errors"], [])
        self.assertTrue(Path(applied["backup_dir"]).is_dir())
        raw = json.loads((self.data_dir / "watchlist.json").read_text(encoding="utf-8"))
        self.assertEqual(raw["记录"][0]["状态"], "待看")
        self.assertEqual(raw["记录"][0]["片名"], "老数据")

    def test_migrate_is_idempotent(self) -> None:
        self.run_cli("init")
        fc.migrate_fields(self.data_dir, "zh", apply_changes=True)
        first = (self.data_dir / "watchlist.json").read_text(encoding="utf-8")
        fc.migrate_fields(self.data_dir, "zh", apply_changes=True)
        self.assertEqual((self.data_dir / "watchlist.json").read_text(encoding="utf-8"), first)

    def test_migrate_to_english_switches_config(self) -> None:
        self.run_cli("init")
        fc.migrate_fields(self.data_dir, "en", apply_changes=True)
        config = json.loads((self.data_dir / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(config["field_language"], "en")
        raw = json.loads((self.data_dir / "watchlist.json").read_text(encoding="utf-8"))
        self.assertIn("items", raw)
        self.assertEqual(fc.field_language(self.data_dir), "en")

    def test_field_language_override_wins(self) -> None:
        self.run_cli("--field-language", "en", "init")
        raw = json.loads((self.data_dir / "watchlist.json").read_text(encoding="utf-8"))
        self.assertIn("items", raw)

    def test_validation_error_uses_visible_field_name(self) -> None:
        self.run_cli("init")
        with self.assertRaises(fc.FilmCuratorError) as caught:
            fc.validate_item({"id": "it_1", "title": "缺状态", "content_type": "movie",
                              "status": "", "added_date": "2026-01-01"})
        self.assertIn("状态", str(caught.exception))

    def test_work_and_fit_ratings_are_validated(self) -> None:
        item = {"id": "it_1", "title": "评分测试", "content_type": "movie", "status": "want", "added_date": "2026-01-01", "work_rating": 8.5, "fit_rating": 7}
        fc.validate_item(item)
        with self.assertRaises(fc.FilmCuratorError) as caught:
            fc.validate_item({**item, "work_rating": 11})
        self.assertIn("我的评分", str(caught.exception))

    def test_find_uses_dedup_rules_and_separates_partial_hits(self) -> None:
        """按片名查记录要用判重那套规范化，且精确与包含分开，别把「X系列」当成「X」改掉。"""
        self.run_cli("init")
        self.run_cli("add", "--title", "小森林")
        self.run_cli("add", "--title", "小森林系列")
        result = fc.find_items_by_title(self.data_dir, "《小森 林》")
        self.assertEqual(result["exact_count"], 1)
        self.assertEqual(result["exact_matches"][0]["title"], "小森林")
        self.assertEqual([hit["title"] for hit in result["partial_matches"]], ["小森林系列"])
        self.assertEqual(fc.find_items_by_title(self.data_dir, "小森林", exact=True)["partial_count"], 0)
        self.assertEqual(fc.find_items_by_title(self.data_dir, "没有这部片")["exact_count"], 0)

    def test_add_with_rating_records_watched_in_one_call(self) -> None:
        """「看完了，X 分」应当一条命令写完片单、历史和画像，不必 add 再 complete。"""
        self.run_cli("init")
        self.run_cli("add", "--title", "一步记完", "--work-rating", "8.5", "--comment", "顺手记的")
        created = fc.find_items_by_title(self.data_dir, "一步记完")["exact_matches"][0]
        self.assertEqual(created["status"], "watched")
        self.assertEqual(created["work_rating"], 8.5)
        self.assertTrue(created["watched_date"])
        history = fc.read_json(self.data_dir / "history.json")["events"]
        self.assertEqual([event["title"] for event in history], ["一步记完"])
        self.assertEqual(history[0]["work_rating"], 8.5)
        self.assertEqual(fc.read_json(self.data_dir / "user_profile.json")["ratings_count"], 1)

    def test_summary_reads_both_old_and_new_rating_keys(self) -> None:
        """月度均分要算得出来：新事件写 work_rating，合并前的老事件写 rating。"""
        self.run_cli("init")
        self.run_cli("add", "--title", "新写法", "--work-rating", "8", "--watched-date", "2026-08-10")
        history_path = self.data_dir / "history.json"
        history = fc.read_json(history_path)
        history["events"].append({
            "item_id": "legacy-1", "title": "老写法",
            "watched_date": "2026-08-11", "rating": 6.0, "comment": "",
        })
        fc.write_json(history_path, history)
        summary = fc.build_summary(self.data_dir, "2026-08")
        self.assertEqual(summary["watched_count"], 2)
        self.assertEqual(summary["average_rating"], 7.0)

    def test_next_skill_trigger_auto_enriches_missing_metadata(self) -> None:
        self.run_cli("init")
        write(self.data_dir / "watchlist.json", {
            "schema_version": 1,
            "items": [{"id": "m1", "title": "待补全电影", "content_type": "movie", "status": "want", "added_date": "2026-08-21"}],
        })
        original = fc.lookup_douban_metadata
        fc.lookup_douban_metadata = lambda title, year=None: {
            "synopsis": "自动补全简介",
            "genres": ["剧情"],
            "director": "自动导演",
            "duration_min": 98,
            "language": "中文",
        }
        try:
            self.assertEqual(self.run_cli("validate"), 0)
        finally:
            fc.lookup_douban_metadata = original
        item = fc.read_json(self.data_dir / "watchlist.json")["items"][0]
        self.assertEqual(item["synopsis"], "自动补全简介")
        self.assertEqual(item["director"], "自动导演")

    def test_subtitle_sensitive_language_mode_changes_ranking(self) -> None:
        self.run_cli("init")
        fc.update_profile(self.data_dir, {"preferred_languages": ["中文"]})
        candidates = [
            {"id": "foreign", "title": "外语片", "content_type": "movie", "status": "want", "added_date": "2026-08-21", "language": "法语"},
            {"id": "local", "title": "中文片", "content_type": "movie", "status": "want", "added_date": "2026-08-21", "language": "中文"},
        ]
        ranked = fc.rank_candidates(self.data_dir, candidates, 2, "", None, language_mode="subtitle_sensitive")
        self.assertEqual(ranked[0]["title"], "中文片")
        self.assertIn("subtitle-light context favors easier language", ranked[1]["score_reasons"])

    def test_unknown_duration_is_demoted_not_excluded(self) -> None:
        """时长未知的记录不能因为用户说了可用时长就被全部排除，只该排在后面。"""
        self.run_cli("init")
        candidates = [
            {"id": "known", "title": "有时长的", "content_type": "movie", "status": "want", "added_date": "2026-08-21", "duration_min": 100},
            {"id": "unknown", "title": "没时长的", "content_type": "movie", "status": "want", "added_date": "2026-08-21"},
            {"id": "toolong", "title": "确切超时的", "content_type": "movie", "status": "want", "added_date": "2026-08-21", "duration_min": 200},
        ]
        ranked = fc.rank_candidates(self.data_dir, candidates, 5, "", 120)
        titles = [item["title"] for item in ranked]
        self.assertIn("有时长的", titles)
        self.assertIn("没时长的", titles)
        self.assertNotIn("确切超时的", titles)  # 确切超时的才排除
        self.assertLess(titles.index("有时长的"), titles.index("没时长的"))
        unknown = next(item for item in ranked if item["title"] == "没时长的")
        self.assertIn("duration unknown, may not fit available time", unknown["score_reasons"])

    def test_candidate_pool_survey_gives_stats_and_search(self) -> None:
        """候选待看清单要能低成本查阅：先看统计，再按关键词筛，不必整份读出来。"""
        self.run_cli("init")
        fc.merge_candidate_pool(
            self.data_dir,
            [
                {"title": "候选纪录片", "content_type": "documentary", "director": "某导演"},
                {"title": "候选剧集", "content_type": "series", "genres": ["剧情"]},
            ],
            apply_changes=True,
        )
        stats = fc.survey_candidate_pool(self.data_dir, stats_only=True)
        self.assertEqual(stats["total"], 2)
        self.assertNotIn("items", stats)
        self.assertIn("documentary", stats["content_types"])

        full = fc.survey_candidate_pool(self.data_dir)
        self.assertEqual(len(full["items"]), 2)

        by_title = fc.survey_candidate_pool(self.data_dir, "候选纪录片")
        self.assertEqual(by_title["matched"], 1)
        self.assertEqual(by_title["items"][0]["title"], "候选纪录片")

        by_director = fc.survey_candidate_pool(self.data_dir, "某导演")
        self.assertEqual(by_director["matched"], 1)

        limited = fc.survey_candidate_pool(self.data_dir, limit=1)
        self.assertEqual(len(limited["items"]), 1)
        self.assertTrue(limited["truncated"])

    def test_candidate_pool_does_not_enter_watchlist_until_adopted(self) -> None:
        self.run_cli("init")
        original = fc.lookup_douban_metadata
        fc.lookup_douban_metadata = lambda title, year=None: {"genres": ["剧情"], "language": "中文"}
        try:
            preview = fc.merge_candidate_pool(self.data_dir, [{"title": "候选电影"}], apply_changes=False)
            applied = fc.merge_candidate_pool(self.data_dir, [{"title": "候选电影"}], apply_changes=True)
        finally:
            fc.lookup_douban_metadata = original
        self.assertFalse(preview["applied"])
        self.assertEqual(applied["added"], 1)
        self.assertEqual(fc.read_json(self.data_dir / "watchlist.json")["items"], [])
        pool_items = fc.load_candidate_pool(self.data_dir)
        self.assertEqual(pool_items[0]["title"], "候选电影")
        adopted = fc.adopt_candidate(self.data_dir, pool_items[0])
        self.assertEqual(adopted["title"], "候选电影")
        self.assertEqual(fc.read_json(self.data_dir / "watchlist.json")["items"][0]["status"], "want")


class BackendTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name) / "data"
        fc.FIELD_LANGUAGE_OVERRIDE = None
        fc._FIELD_LANGUAGE_CACHE.clear()
        fc.ACTIVE_DATA_DIR = self.data_dir

    def tearDown(self) -> None:
        fc.FIELD_LANGUAGE_OVERRIDE = None
        fc._FIELD_LANGUAGE_CACHE.clear()
        fc.ACTIVE_DATA_DIR = fc.DEFAULT_DATA_DIR
        self.tmp.cleanup()

    def run_cli(self, *argv: str) -> int:
        return fc.main(["--data-dir", str(self.data_dir), *argv])

    def _seed(self) -> None:
        """建一条已看记录 + 一条候选，供导出导入对账。"""
        self.run_cli("init")
        self.run_cli("add", "--title", "特洛伊", "--work-rating", "8", "--comment", "史诗感足")
        fc.merge_candidate_pool(
            self.data_dir,
            [{"id": "cand_1", "title": "候选片", "content_type": "movie", "added_date": "2026-08-21"}],
            apply_changes=True,
        )

    def test_backend_export_shapes_rows(self) -> None:
        self._seed()
        payload = fc.backend_export(self.data_dir)
        self.assertEqual(sorted(payload.keys()), ["history", "watchlist"])
        self.assertEqual(len(payload["watchlist"]), 1)  # 只含正式片单，候选不上云
        self.assertEqual(len(payload["history"]), 1)
        watch = {row["片名"]: row for row in payload["watchlist"]}
        self.assertEqual(watch["特洛伊"]["状态"], "已看")
        self.assertEqual(watch["特洛伊"]["我的评分"], 8.0)
        self.assertEqual(watch["特洛伊"]["已删除"], False)
        self.assertNotIn("候选片", watch)
        self.assertEqual(payload["history"][0]["片名"], "特洛伊")
        self.assertNotIn("示例数据", payload["history"][0])

    def test_backend_export_skips_examples(self) -> None:
        self.run_cli("init")
        watchlist = fc.read_json(self.data_dir / "watchlist.json")
        watchlist["items"].append({"id": "ex_1", "title": "示例片", "content_type": "movie", "status": "want", "is_example": True})
        fc.write_json(self.data_dir / "watchlist.json", watchlist)
        payload = fc.backend_export(self.data_dir)
        self.assertEqual(len(payload["watchlist"]), 0)

    def test_backend_import_adds_and_updates(self) -> None:
        self._seed()
        trojan_id = fc.find_items_by_title(self.data_dir, "特洛伊")["exact_matches"][0]["id"]
        rows = {
            "watchlist": [
                # 已有记录：带本地编号改评分
                {"本地编号": trojan_id, "片名": "特洛伊", "状态": "已看", "我的评分": 9},
                # 新记录：没本地编号
                {"片名": "欢迎来到龙餐馆", "状态": "已看", "我的评分": 9.5},
            ],
            "history": [],
        }
        import_path = self.data_dir.parent / "pull.json"
        write(import_path, rows)
        result = fc.backend_import(self.data_dir, import_path)
        self.assertGreaterEqual(result["added"], 1)
        self.assertGreaterEqual(result["updated"], 1)
        items = fc.read_json(self.data_dir / "watchlist.json")["items"]
        by_title = {item["title"]: item for item in items}
        self.assertEqual(by_title["特洛伊"]["work_rating"], 9)
        self.assertEqual(by_title["欢迎来到龙餐馆"]["work_rating"], 9.5)

    def test_backend_import_deletes_via_marker(self) -> None:
        self._seed()
        trojan_id = fc.find_items_by_title(self.data_dir, "特洛伊")["exact_matches"][0]["id"]
        rows = {
            "watchlist": [{"本地编号": trojan_id, "片名": "特洛伊", "已删除": True}],
            "history": [],
        }
        import_path = self.data_dir.parent / "pull.json"
        write(import_path, rows)
        result = fc.backend_import(self.data_dir, import_path)
        self.assertGreaterEqual(result["removed"], 1)
        titles = [item["title"] for item in fc.read_json(self.data_dir / "watchlist.json")["items"]]
        self.assertNotIn("特洛伊", titles)

    def test_backend_import_leaves_candidate_pool_untouched(self) -> None:
        self._seed()
        before = len(fc.read_json(self.data_dir / "candidate_pool.json")["items"])
        rows = {"watchlist": [{"片名": "新片", "状态": "待看"}], "history": []}
        import_path = self.data_dir.parent / "pull.json"
        write(import_path, rows)
        fc.backend_import(self.data_dir, import_path)
        after = len(fc.read_json(self.data_dir / "candidate_pool.json")["items"])
        self.assertEqual(before, after)

    def test_backend_import_history_skips_rows_without_key(self) -> None:
        self._seed()
        rows = {
            "watchlist": [],
            "history": [{"片名": "特洛伊", "看完日期": "2026-08-20", "我的评分": 8, "短评": "补一句"}],
        }
        import_path = self.data_dir.parent / "pull.json"
        write(import_path, rows)
        result = fc.backend_import(self.data_dir, import_path)
        self.assertEqual(result["skipped_history"], 1)
        history = fc.read_json(self.data_dir / "history.json")["events"]
        self.assertEqual(len(history), 1)

    def test_storage_first_use_asks_user(self) -> None:
        self.run_cli("init")
        resolved = fc.resolve_storage_provider(self.data_dir)
        self.assertTrue(resolved["ask_user"])
        self.assertEqual(resolved["reason"], "first_use")

    def test_storage_bind_one_provider_becomes_default(self) -> None:
        self.run_cli("init")
        status = fc.bind_storage(self.data_dir, "feishu", watchlist_url="https://example.com/bitable")
        self.assertEqual(status["bound_providers"], ["feishu"])
        self.assertEqual(status["default_provider"], "feishu")
        self.assertFalse(status["needs_choice"])
        resolved = fc.resolve_storage_provider(self.data_dir)
        self.assertEqual(resolved["provider"], "feishu")
        self.assertFalse(resolved["ask_user"])

    def test_storage_both_bound_needs_default_choice(self) -> None:
        self.run_cli("init")
        fc.bind_storage(self.data_dir, "feishu", watchlist_url="https://feishu.example/app")
        fc.bind_storage(self.data_dir, "notion", watchlist_url="https://notion.example/db")
        resolved = fc.resolve_storage_provider(self.data_dir)
        self.assertTrue(resolved["ask_user"])
        self.assertEqual(resolved["reason"], "both_bound")
        fc.set_default_storage(self.data_dir, "notion")
        resolved = fc.resolve_storage_provider(self.data_dir)
        self.assertEqual(resolved["provider"], "notion")
        self.assertFalse(resolved["ask_user"])

    def test_backend_template_includes_feishu_and_notion_specs(self) -> None:
        template = fc.backend_template()
        self.assertIn("片名", [field["field_name"] for field in template["feishu"]["watchlist_fields"]])
        self.assertIn("片名", template["notion"]["watchlist_properties"])
        self.assertEqual(template["notion"]["watchlist_properties"]["片名"], {"title": {}})
        self.assertEqual(template["create_name"], "Film Curator 观影记录本")

    def test_column_diff_flags_missing_required(self) -> None:
        diff = fc.diff_template_columns("watchlist", ["片名", "状态"])
        self.assertFalse(diff["compatible"])
        self.assertIn("本地编号", diff["required_missing"])
        ok = fc.diff_template_columns("watchlist", ["本地编号", "片名", "状态", "已删除", "额外列"])
        self.assertTrue(ok["compatible"])
        self.assertIn("额外列", ok["extra"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
