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
        english = fc.parse_assignments(["status=watched", "user_rating=8.5", "plan_period=month"])
        self.assertEqual(chinese, english)
        self.assertEqual(chinese["status"], "watched")


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
        self.assertIn("作品评价", str(caught.exception))

    def test_import_enriches_missing_metadata_without_real_network(self) -> None:
        self.run_cli("init")
        source = self.data_dir / "incoming.json"
        write(source, {"items": [{"id": "m1", "title": "测试电影", "status": "want", "content_type": "movie", "added_date": "2026-08-21"}]})
        original = fc.lookup_online_metadata
        fc.lookup_online_metadata = lambda title, year=None: {
            "synopsis": "一部用于测试的电影简介",
            "genres": ["剧情"],
            "director": "测试导演",
            "duration_min": 101,
            "language": "中文",
        }
        try:
            result = fc.import_data(self.data_dir, source, "skip", apply_changes=True)
        finally:
            fc.lookup_online_metadata = original
            fc.lookup_online_metadata.cache_clear()
        self.assertTrue(result["applied"])
        self.assertEqual(result["metadata_enriched_count"], 1)
        item = fc.read_json(self.data_dir / "watchlist.json")["items"][0]
        self.assertEqual(item["synopsis"], "一部用于测试的电影简介")
        self.assertEqual(item["genres"], ["剧情"])
        self.assertEqual(item["language"], "中文")

    def test_import_can_skip_metadata_enrichment(self) -> None:
        self.run_cli("init")
        source = self.data_dir / "incoming.json"
        write(source, {"items": [{"id": "m1", "title": "不补全电影", "status": "want", "content_type": "movie", "added_date": "2026-08-21"}]})
        original = fc.lookup_online_metadata
        fc.lookup_online_metadata = lambda title, year=None: {"synopsis": "不应该出现"}
        try:
            result = fc.import_data(self.data_dir, source, "skip", apply_changes=True, enrich_metadata=False)
        finally:
            fc.lookup_online_metadata = original
            fc.lookup_online_metadata.cache_clear()
        self.assertEqual(result["metadata_enriched_count"], 0)
        item = fc.read_json(self.data_dir / "watchlist.json")["items"][0]
        self.assertEqual(item.get("synopsis", ""), "")

    def test_next_skill_trigger_auto_enriches_missing_metadata(self) -> None:
        self.run_cli("init")
        write(self.data_dir / "watchlist.json", {
            "schema_version": 1,
            "items": [{"id": "m1", "title": "待补全电影", "content_type": "movie", "status": "want", "added_date": "2026-08-21"}],
        })
        original = fc.lookup_online_metadata
        fc.lookup_online_metadata = lambda title, year=None: {
            "synopsis": "自动补全简介",
            "genres": ["剧情"],
            "director": "自动导演",
            "duration_min": 98,
            "language": "中文",
        }
        try:
            self.assertEqual(self.run_cli("validate"), 0)
        finally:
            fc.lookup_online_metadata = original
            fc.lookup_online_metadata.cache_clear()
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

    def test_candidate_pool_does_not_enter_watchlist_until_adopted(self) -> None:
        self.run_cli("init")
        original = fc.lookup_online_metadata
        fc.lookup_online_metadata = lambda title, year=None: {"genres": ["剧情"], "language": "中文"}
        try:
            preview = fc.merge_candidate_pool(self.data_dir, [{"title": "候选电影"}], apply_changes=False)
            applied = fc.merge_candidate_pool(self.data_dir, [{"title": "候选电影"}], apply_changes=True)
        finally:
            fc.lookup_online_metadata = original
            fc.lookup_online_metadata.cache_clear()
        self.assertFalse(preview["applied"])
        self.assertEqual(applied["added"], 1)
        self.assertEqual(fc.read_json(self.data_dir / "watchlist.json")["items"], [])
        pool_items = fc.load_candidate_pool(self.data_dir)
        self.assertEqual(pool_items[0]["title"], "候选电影")
        adopted = fc.adopt_candidate(self.data_dir, pool_items[0])
        self.assertEqual(adopted["title"], "候选电影")
        self.assertEqual(fc.read_json(self.data_dir / "watchlist.json")["items"][0]["status"], "want")


if __name__ == "__main__":
    unittest.main(verbosity=2)
