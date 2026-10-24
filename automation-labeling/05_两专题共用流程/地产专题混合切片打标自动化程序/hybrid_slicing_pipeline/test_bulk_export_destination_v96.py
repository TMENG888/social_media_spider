"""Offline destination routing tests; no workbook authoring or API requests."""
import contextlib
import io
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import verify_bulk_v96 as target


class Sheet:
    def __init__(self, rows):
        self.rows = rows

    def iter_rows(self, min_row=1, max_row=None, values_only=False):
        return iter(self.rows[min_row - 1:max_row])


class Book:
    def __init__(self, name, topic):
        sources = [["record_id", "来源类型", "原始主体", "评论平台文章id"]]
        sources += [[f"A{i}", "文章", "真实文章测试占位", None] for i in range(500)]
        if topic == target.T2:
            sources += [[f"C{i}", "评论", "真实评论测试占位", "parent"] for i in range(956)]
        main = [
            ["unit_id", "record_id", "标签明细", "打标说明",
             "具体产品做法" if topic == target.T1 else "观点摘要",
             "来源类型", "原始摘录", "映射文章id"],
            ["U1", "A0" if topic == target.T1 else "C0",
             json.dumps([{"标签路径ID": "VOC-0377"}]), "有据说明",
             "具体做法" if topic == target.T1 else "观点摘要",
             "文章" if topic == target.T1 else "评论",
             "真实评论测试占位" if topic == target.T2 else None,
             "parent" if topic == target.T2 else None],
        ]
        dictionary = [[], [], [], [], ["标签路径ID", "打标说明"],
                      ["VOC-0377", "会所内健身房，无需具体器械"]]
        self.sheets = {
            "源记录与文章关联": Sheet(sources),
            name: Sheet(main),
            "专题一标签体系" if topic == target.T1 else "专题二标签体系": Sheet(dictionary),
        }

    def __getitem__(self, key):
        return self.sheets[key]

    def close(self):
        pass


class ExportDestinationTests(unittest.TestCase):
    def run_route(self, workbook_dir=None, exists=True, size=123):
        generation = Path("C:/test-checkpoints")
        destination = workbook_dir or generation
        loaded, saved = [], []

        def read_payload(path, *args, **kwargs):
            self.assertEqual(path.parent, generation)
            name = path.name.removesuffix("_workbook_payload.json")
            return json.dumps({"filename": name + "_500篇文章批量交付.xlsx",
                               "tables": {name: [{}]}})

        def load_book(path, **kwargs):
            self.assertEqual(path.parent, destination)
            self.assertEqual(kwargs, {"read_only": True, "data_only": True})
            loaded.append(path)
            name = path.name.removesuffix("_500篇文章批量交付.xlsx")
            return Book(name, target.T1 if name == "产品信息单元" else target.T2)

        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(Path, "read_text", new=read_payload))
            stack.enter_context(patch.object(Path, "is_file", return_value=exists))
            stack.enter_context(patch.object(Path, "stat", return_value=SimpleNamespace(st_size=size)))
            stack.enter_context(patch.object(Path, "resolve", new=lambda path: path))
            stack.enter_context(patch.object(target, "load_taxonomy", return_value=[{"tag_id": "VOC-0377"}]))
            stack.enter_context(patch.object(target, "label_json", return_value={"标签路径ID": "VOC-0377"}))
            stack.enter_context(patch.object(target.openpyxl, "load_workbook", side_effect=load_book))
            stack.enter_context(patch.object(target, "save_json", side_effect=lambda path, data: saved.append((path, data))))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            target.verify(generation, Path("taxonomy.xlsx"), workbook_dir)
        self.assertEqual(len(loaded), 2)
        self.assertEqual(saved[0][0], generation / "saved_workbooks_verification.json")
        self.assertTrue(saved[0][1]["passed"])
        self.assertEqual(saved[0][1]["workbook_dir"], str(destination))
        self.assertEqual([r["comments"] for r in saved[0][1]["workbooks"]], [0, 956])
        self.assertTrue(all(Path(r["path"]).parent == destination for r in saved[0][1]["workbooks"]))

    def test_separate_d_drive_destination(self):
        self.run_route(Path("D:/test-delivery"))

    def test_default_destination_unchanged(self):
        self.run_route()

    def test_missing_workbook_rejected(self):
        with self.assertRaisesRegex(AssertionError, "Missing or empty saved workbook"):
            self.run_route(Path("D:/test-delivery"), exists=False)

    def test_empty_workbook_rejected(self):
        with self.assertRaisesRegex(AssertionError, "Missing or empty saved workbook"):
            self.run_route(Path("D:/test-delivery"), size=0)


if __name__ == "__main__":
    unittest.main()
