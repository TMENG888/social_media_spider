"""Offline safety tests: no API, actual checkpoint writes, or workbook exports."""
import contextlib
import io
import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import resume_missing_v96 as recovery


class RecoverySafetyTests(unittest.TestCase):
    def setUp(self):
        self.output = Path("C:/frozen-checkpoints")
        self.doc = {"record_id": "SOURCE-1", "topic": "topic", "kind": "文章", "text": "原文"}
        self.result = {"document": {**self.doc, "semantic_segments": []}}

    def test_existing_stage_never_regenerated(self):
        generate = Mock(side_effect=AssertionError("must not regenerate"))
        with patch.object(Path, "exists", return_value=True), patch.object(
                recovery, "read_checkpoint", return_value=self.result), patch.object(
                recovery.b, "save_json") as save:
            result = recovery.checkpoint(self.output, "04_final", self.doc, "signature",
                                         None, generate)
        self.assertIs(result, self.result)
        generate.assert_not_called()
        save.assert_not_called()

    def test_metadata_extensions_preserve_original_source(self):
        saved = {"bulk_signature": recovery.expected_signature("sig", self.doc, None),
                 "result": self.result}
        with patch.object(Path, "read_text", return_value=json.dumps(saved)):
            actual = recovery.read_checkpoint(self.output, "01_mapreduce", self.doc, "sig", None)
        self.assertEqual(actual, self.result)

    def test_mismatched_signature_is_not_overwritten(self):
        saved = {"bulk_signature": "different", "result": self.result}
        with patch.object(Path, "exists", return_value=True), patch.object(
                Path, "read_text", return_value=json.dumps(saved)), patch.object(
                recovery.b, "save_json") as save:
            with self.assertRaisesRegex(RuntimeError, "signature differs"):
                recovery.checkpoint(self.output, "01_mapreduce", self.doc, "sig", None, Mock())
        save.assert_not_called()

    def test_changed_source_is_rejected(self):
        result = {"document": {**self.doc, "text": "错误原文"}}
        saved = {"bulk_signature": recovery.expected_signature("sig", self.doc, None),
                 "result": result}
        with patch.object(Path, "read_text", return_value=json.dumps(saved)):
            with self.assertRaisesRegex(RuntimeError, "document differs"):
                recovery.read_checkpoint(self.output, "01_mapreduce", self.doc, "sig", None)

    def test_concurrent_checkpoint_is_not_overwritten(self):
        with patch.object(Path, "exists", side_effect=[False, True]), patch.object(
                recovery.b, "save_json") as save:
            with self.assertRaisesRegex(RuntimeError, "Concurrent checkpoint"):
                recovery.checkpoint(self.output, "04_final", self.doc, "sig", None,
                                    lambda: self.result)
        save.assert_not_called()

    def test_complete_inventory_has_zero_generation_calls(self):
        with patch.object(Path, "exists", return_value=True), patch.object(
                recovery, "read_checkpoint", return_value=self.result) as read, patch.object(
                recovery.original, "validate_final") as validate, contextlib.redirect_stdout(io.StringIO()):
            result = recovery.inventory(self.output, [self.doc], "sig", [])
        self.assertEqual(result["complete_ids"], ["SOURCE-1"])
        self.assertEqual(result["missing_ids"], [])
        self.assertEqual(result["api_requests_sent_during_inventory"], 0)
        self.assertEqual(read.call_count, 4)
        validate.assert_called_once()

    def test_orphaned_later_stage_is_rejected(self):
        with patch.object(Path, "exists", side_effect=[False, True]):
            with self.assertRaisesRegex(RuntimeError, "Orphaned"):
                recovery.inventory(self.output, [self.doc], "sig", [])


if __name__ == "__main__":
    unittest.main()
