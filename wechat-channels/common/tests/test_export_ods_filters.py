import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SOURCE = Path(__file__).parents[1] / "src" / "channels_pc_collector.py"
SPEC = importlib.util.spec_from_file_location("channels_pc_collector_export_tests", SOURCE)
collector = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = collector
SPEC.loader.exec_module(collector)


class ExportOdsFilterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.connection = collector.init_state(root / "state.sqlite")
        rows = [
            ("key-a", "专题一", "中海 住宅", "https://weixin.qq.com/sph/a", "标题A"),
            ("key-b", "专题一", "中海 住宅", "https://weixin.qq.com/sph/b", "标题B"),
            ("key-c", "专题二", "北京臻澐", "https://weixin.qq.com/sph/c", "标题C"),
        ]
        self.connection.executemany(
            """
            INSERT INTO captured_article(
                article_key, project, keyword, url, captured_at, title,
                image_count, video_count
            ) VALUES(?, ?, ?, ?, '2026-09-30T10:00:00', ?, 0, 1)
            """,
            rows,
        )
        self.connection.executemany(
            """
            INSERT INTO captured_comment(
                comment_key, article_key, project, keyword, article_url,
                captured_at
            ) VALUES(?, ?, ?, ?, ?, '2026-09-30T10:00:00')
            """,
            [
                ("comment-a", "key-a", "专题一", "中海 住宅", "https://weixin.qq.com/sph/a"),
                ("comment-c", "key-c", "专题二", "北京臻澐", "https://weixin.qq.com/sph/c"),
            ],
        )
        self.connection.executemany(
            """
            INSERT INTO video_dead_letter(
                keyword, fingerprint, project, retry_count, created_at, updated_at
            ) VALUES(?, ?, ?, 1, '2026-09-30T10:00:00', '2026-09-30T10:00:00')
            """,
            [
                ("中海 住宅", "fingerprint-a", "专题一"),
                ("北京臻澐", "fingerprint-c", "专题二"),
            ],
        )
        self.connection.commit()
        self.root = root

    def tearDown(self):
        self.connection.close()
        self.temporary.cleanup()

    def test_keyword_filter(self):
        result = collector.export_ods_local(
            self.root / "keyword", self.connection, ["中海 住宅"], None,
        )
        self.assertEqual(result["records"], 2)
        self.assertEqual(result["comments"], 1)
        self.assertEqual(result["dead_letters"], 1)

    def test_article_key_filter(self):
        result = collector.export_ods_local(
            self.root / "article", self.connection, None, ["key-c"],
        )
        self.assertEqual(result["records"], 1)
        self.assertEqual(result["comments"], 1)
        # Dead letters have no article_key column, so they remain unfiltered.
        self.assertEqual(result["dead_letters"], 2)

    def test_keyword_and_article_key_filter_do_not_reuse_bindings(self):
        result = collector.export_ods_local(
            self.root / "both", self.connection, ["中海 住宅"], ["key-a"],
        )
        self.assertEqual(result["records"], 1)
        self.assertEqual(result["comments"], 1)
        self.assertEqual(result["dead_letters"], 1)


if __name__ == "__main__":
    unittest.main()
