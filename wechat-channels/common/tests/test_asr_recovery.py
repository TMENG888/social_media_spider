import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


SOURCE = Path(__file__).parents[1] / "src" / "channels_pc_collector.py"
SPEC = importlib.util.spec_from_file_location("channels_pc_collector", SOURCE)
collector = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = collector
SPEC.loader.exec_module(collector)


class Segment:
    def __init__(self, text):
        self.text = text


class Info:
    def __init__(self, speech):
        self.duration_after_vad = speech


class FakeModel:
    def __init__(self):
        self.calls = []

    def transcribe(self, _path, **options):
        self.calls.append(options)
        if options.get("vad_filter"):
            return iter([Segment("Amara.org")]), Info(0.0)
        return iter([Segment("开头三秒也应完整保留，随后继续介绍项目。")]), Info(4.0)


class FakeProcess:
    def __init__(self, line):
        self.stdout = io.StringIO(line)


class FakeWindowElementInfo:
    class_name = "Chrome_WidgetWin_0"

    def __init__(self, handle):
        self.handle = handle


class FakeDocument:
    def __init__(self, name):
        self.name = name

    def window_text(self):
        return self.name


class FakeDetachedWindow:
    def __init__(self, handle, document_name):
        self.handle = handle
        self.document_name = document_name
        self.element_info = FakeWindowElementInfo(handle)
        self.closed = False
        self.focused = False

    def descendants(self, control_type=None):
        if control_type == "Document":
            return [FakeDocument(self.document_name)]
        return []

    def window_text(self):
        return "微信"

    def maximize(self):
        return None

    def set_focus(self):
        self.focused = True

    def close(self):
        self.closed = True


class FakeTextControl:
    def __init__(self, text):
        self.text = text

    def window_text(self):
        return self.text


class FakeTextSurface:
    def __init__(self, *texts):
        self.texts = texts

    def descendants(self, control_type=None):
        return [FakeTextControl(text) for text in self.texts]


class FakeProcessSurface:
    class ElementInfo:
        process_id = 3008

    element_info = ElementInfo()


class AsrRecoveryTests(unittest.TestCase):
    def test_load_more_recovers_same_keyword_when_search_surface_disappears(self):
        surface = MagicMock()
        surface.descendants.return_value = []
        rect = MagicMock()
        rect.left, rect.top, rect.right, rect.bottom = 0, 0, 1000, 800
        rect.width.return_value = 1000
        rect.height.return_value = 800
        surface.rectangle.return_value = rect
        with patch.object(
            collector, "get_search_window",
            side_effect=[collector.SearchWindowUnavailableError("gone")] + [surface] * 6,
        ), patch.object(
            collector, "search_result_buttons", side_effect=[[], [], [], []],
        ), patch.object(
            collector, "search_in_web", return_value=None,
        ) as recover, patch.object(
            collector.mouse, "scroll", return_value=None,
        ), patch.object(
            collector.time, "sleep", return_value=None,
        ):
            results, grew = collector.load_more_search_results(
                surface, 10,
                {
                    "load_more_rounds": 3,
                    "load_more_search_recovery_attempts": 1,
                    "load_more_recovery_scroll_cap": 2,
                    "jitter_enabled": False,
                    "wait_load_more": 0,
                },
                keyword="中海 住宅",
            )
        self.assertEqual(results, [])
        self.assertFalse(grew)
        recover.assert_called_once_with("中海 住宅", unittest.mock.ANY)

    def test_background_asr_recovery_is_scoped_to_current_keyword(self):
        with tempfile.TemporaryDirectory() as temporary:
            state_db = Path(temporary) / "state.sqlite"
            connection = collector.init_state(state_db)
            now = "2026-10-01T00:00:00"
            for index, keyword in enumerate(("关键词甲", "关键词乙"), start=1):
                wav = Path(temporary) / f"{index}.wav"
                wav.write_bytes(b"RIFF")
                payload = {
                    "wav_path": str(wav), "title": keyword,
                    "duration": 1, "capture_seconds": 1,
                    "recorder_seconds": 1, "recorder_audit": {},
                    "seeked": False, "reloaded_from_start": False,
                    "source": "test", "fingerprint": f"fp-{index}",
                    "project": "测试",
                }
                connection.execute(
                    "INSERT INTO asr_job(article_key,keyword,wav_path,payload_json,status,attempts,created_at,updated_at) "
                    "VALUES(?,?,?,?, 'pending',0,?,?)",
                    (f"article-{index}", keyword, str(wav), json.dumps(payload), now, now),
                )
            connection.commit()
            connection.close()
            with patch.object(
                collector, "transcribe_pending_client_audio", return_value="",
            ) as transcribe:
                queue = collector.BackgroundAsrQueue(
                    state_db, {"asr_job_max_attempts": 3},
                    recovery_keyword="关键词甲",
                )
                queue.close_and_wait()
            self.assertEqual(transcribe.call_count, 1)

    def test_exact_retry_without_article_key_does_not_drain_old_asr_jobs(self):
        with tempfile.TemporaryDirectory() as temporary:
            state_db = Path(temporary) / "state.sqlite"
            connection = collector.init_state(state_db)
            wav = Path(temporary) / "old.wav"
            wav.write_bytes(b"RIFF")
            payload = {
                "wav_path": str(wav), "title": "旧任务",
                "duration": 1, "capture_seconds": 1,
                "recorder_seconds": 1, "recorder_audit": {},
                "seeked": False, "reloaded_from_start": False,
                "source": "test", "fingerprint": "old-fp", "project": "测试",
            }
            connection.execute(
                "INSERT INTO asr_job(article_key,keyword,wav_path,payload_json,status,attempts,created_at,updated_at) "
                "VALUES(?,?,?,?, 'pending',0,?,?)",
                ("old-article", "同一关键词", str(wav), json.dumps(payload),
                 "2026-10-01T00:00:00", "2026-10-01T00:00:00"),
            )
            connection.commit()
            connection.close()
            with patch.object(
                collector, "transcribe_pending_client_audio", return_value="",
            ) as transcribe:
                queue = collector.BackgroundAsrQueue(
                    state_db, {}, recovery_keyword="同一关键词",
                    recovery_article_keys=set(),
                )
                queue.close_and_wait()
            transcribe.assert_not_called()

    def test_exact_retry_card_scan_does_not_take_periodic_video_breaks(self):
        source = SOURCE.read_text(encoding="utf-8-sig")
        self.assertIn(
            "next_long_break_at is not None\n            # Exact ASR recovery",
            source,
        )
        self.assertIn("and not retry_fingerprint", source)

    def test_jitter_uses_configured_range_only_when_enabled(self):
        with patch.object(collector.random, "uniform", return_value=7.25) as uniform:
            self.assertEqual(
                collector.random_delay_seconds(
                    {"jitter_enabled": True, "probe": [5, 12]},
                    "probe", (1, 2),
                ),
                7.25,
            )
        uniform.assert_called_once_with(5.0, 12.0)
        self.assertEqual(
            collector.random_delay_seconds(
                {"jitter_enabled": False, "probe": [5, 12]},
                "probe", (1, 2),
            ),
            0.0,
        )

    def test_redis_search_token_serializes_only_keyword_submit(self):
        import redis_task_queue

        config = {
            "redis_search_token_enabled": True,
            "redis_search_token_seconds": [12, 25],
            "redis_search_token_fail_open": False,
        }
        environment = {
            "REDIS_URL": "redis://127.0.0.1:6379/0",
            "REDIS_PASSWORD": "secret",
            "REDIS_RUN_ID": "production-run",
            "WECHAT_REDIS_TASK_ID": "topic1:abc",
        }
        with patch.dict(collector.os.environ, environment, clear=False), patch.object(
            collector.random, "uniform", return_value=18.5,
        ), patch.object(
            redis_task_queue, "redis_command", return_value=[1, 0, 123456],
        ) as command:
            self.assertTrue(
                collector.wait_for_distributed_search_token(config, "中海 住宅")
            )
        self.assertEqual(command.call_args.args[2], "EVAL")
        self.assertEqual(
            command.call_args.args[5],
            "wechat:channels:production-run:search-token",
        )
        self.assertEqual(command.call_args.args[6], 18500)

    def test_redis_search_token_waits_for_previous_worker_slot(self):
        import redis_task_queue

        config = {
            "redis_search_token_enabled": True,
            "redis_search_token_seconds": [12, 25],
        }
        environment = {
            "REDIS_URL": "redis://127.0.0.1:6379/0",
            "REDIS_RUN_ID": "production-run",
            "WECHAT_REDIS_TASK_ID": "topic1:abc",
        }
        with patch.dict(collector.os.environ, environment, clear=False), patch.object(
            collector.random, "uniform", return_value=12.0,
        ), patch.object(
            redis_task_queue, "redis_command",
            side_effect=[[0, 1500, 123456], [1, 0, 125000]],
        ), patch.object(
            collector, "interruptible_wait", return_value=True,
        ) as wait:
            self.assertTrue(
                collector.wait_for_distributed_search_token(config, "中海 住宅")
            )
        wait.assert_called_once_with(1.5)

    def test_long_detail_caption_prefix_matches_full_search_caption(self):
        opening = "中海住宅大平层四房两厅两卫南北通透总价优惠适合改善家庭现场实拍"
        full = opening + "后续还有关于园林会所交通和交付标准的大量补充说明" * 4
        matched, score, value = collector.video_detail_identity_match(
            full,
            "中海置业顾问",
            [(opening, "Text", ""), ("中海置业顾问", "Text", "author")],
        )
        self.assertTrue(matched)
        self.assertGreaterEqual(score, 0.96)
        self.assertEqual(value, opening)

    def test_rehydrated_batches_do_not_reset_exhaustion_confirmation(self):
        source = SOURCE.read_text(encoding="utf-8")
        start = source.index("while result_index >= len(results):")
        pagination = source[start:source.index("result = results[result_index]", start)]
        self.assertNotIn("elif grew:\n                no_growth_cycles = 0", pagination)
        self.assertIn("no_growth_cycles += 1", pagination)

    def test_video_category_probe_reacquires_virtualized_controls(self):
        class Rect:
            left, top, right, bottom = 0, 100, 1000, 700

            def width(self):
                return self.right - self.left

            def height(self):
                return self.bottom - self.top

        class Edit:
            def rectangle(self):
                rect = Rect()
                rect.left, rect.top, rect.right, rect.bottom = 100, 100, 600, 140
                return rect

        class Info:
            def __init__(self, class_name):
                self.class_name = class_name

        class Control:
            def __init__(self, label, index, generation, state):
                self.label = label
                self.index = index
                self.generation = generation
                self.state = state
                self.element_info = Info("unit__item active__opacity")

            def rectangle(self):
                rect = Rect()
                rect.left = 130 + self.index * 80 + self.generation * 3
                rect.right = rect.left + 70
                rect.top, rect.bottom = 150, 180
                return rect

            def click_input(self):
                self.state["title"] = self.label
                self.state["clicks"].append((self.generation, self.label))

        class Surface:
            def rectangle(self):
                return Rect()

        state = {"title": "朋友圈", "generation": 0, "clicks": []}
        surface = Surface()

        def controls(*_args, **_kwargs):
            generation = state["generation"]
            state["generation"] += 1
            return [
                Control("全部", 0, generation, state),
                Control("文章", 1, generation, state),
                Control("问一问", 2, generation, state),
                Control("视频", 3, generation, state),
            ]

        with patch.object(collector, "get_search_window", return_value=surface), patch.object(
            collector, "find_search_edit", return_value=Edit()
        ), patch.object(
            collector, "visible_controls", side_effect=controls
        ), patch.object(
            collector, "is_article_results_page", side_effect=lambda _surface: state["title"] == "视频"
        ), patch.object(
            collector, "search_page_titles", side_effect=lambda _surface: [state["title"]]
        ), patch.object(collector.time, "sleep", return_value=None):
            selected, probes = collector.probe_video_category_controls(
                surface, 0, max_probes=8,
            )
        self.assertIs(selected, surface)
        self.assertEqual([label for _generation, label in state["clicks"]], [
            "全部", "文章", "问一问", "视频",
        ])
        self.assertEqual(len(probes), 4)
        self.assertEqual(state["generation"], 4)

    def test_audio_capture_failure_is_not_treated_as_no_content(self):
        source = SOURCE.read_text(encoding="utf-8")
        capture = source[source.index("def capture_client_audio_asr("):source.index("def transcribe_pending_client_audio(")]
        self.assertIn("raise ClientAudioCaptureError", capture)
        self.assertNotIn("return None, duration\n\n\ndef transcribe_pending", capture)

    def test_incomplete_process_audio_retries_process_after_reload_by_default(self):
        config = json.loads((SOURCE.parents[1] / "collector_config.json").read_text(
            encoding="utf-8"
        ))
        source = SOURCE.read_text(encoding="utf-8")
        self.assertTrue(config["client_asr_retry_process_loopback_after_reload"])
        self.assertIn(
            '"client_asr_retry_process_loopback_after_reload",\n                                True,',
            source,
        )

    def test_long_video_sample_skip_is_explicit_and_not_a_production_checkpoint(self):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn("CHANNELS_SAMPLE_MAX_DURATION_SECONDS", source)
        sample_block = source[
            source.index("sample_duration_limit = int("):
            source.index("if (\n                    detail_duration", source.index("sample_duration_limit = int("))
        ]
        self.assertIn("sample_long_video_skipped", sample_block)
        self.assertNotIn("upsert_video_checkpoint", sample_block)

    def test_detail_fields_are_collected_while_recorder_is_active(self):
        events = []

        class ActiveRecorder:
            def poll(self):
                return None

        audit = collector.run_detail_collection_during_recording(
            lambda: events.append("detail_collected"), ActiveRecorder()
        )
        self.assertEqual(events, ["detail_collected"])
        self.assertTrue(audit["recording_active_before"])
        self.assertTrue(audit["recording_active_after"])

    def test_asr_enables_sound_from_stateful_search_card_before_detail(self):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn("config[\"_search_card_audio_enabled\"] = enable_search_card_audio(result)", source)
        self.assertIn('return False, "search_card:audio_requested_unverified"', source)

    def test_search_card_audio_state_survives_silence_retry_reload(self):
        source = SOURCE.read_text(encoding="utf-8")
        capture = source[source.index("def capture_client_audio_asr("):source.index("def transcribe_pending_client_audio(")]
        self.assertEqual(
            capture.count('config.pop("_search_card_audio_enabled", False)'),
            1,
        )
        self.assertGreaterEqual(
            capture.count("assume_audible_from_search_card"),
            3,
        )
        self.assertIn("preflight_audit is not None", capture)

    def test_empty_results_require_explicit_platform_message(self):
        self.assertTrue(collector.has_explicit_no_search_results(
            FakeTextSurface("暂无相关视频，换个关键词试试"),
        ))
        self.assertFalse(collector.has_explicit_no_search_results(
            FakeTextSurface("中海 住宅 - 视频 - 搜一搜"),
        ))

    def test_detail_only_window_does_not_flip_search_layout(self):
        detail = FakeDetachedWindow(202, "视频号")
        collector.SEARCH_LAYOUT = "embedded"
        with patch.object(collector, "web_windows", return_value=[detail]), patch.object(
            collector, "_try_get_main_surface_without_focus", return_value=None,
        ):
            self.assertIsNone(collector.try_get_search_results_window(focus=False))
        self.assertEqual(collector.SEARCH_LAYOUT, "embedded")

    def test_long_fragment_227_seconds_is_marked_partial(self):
        self.assertTrue(collector.asr_output_needs_review(
            "关注棠颂的朋友们大家一定知道", 227,
        ))

    def test_long_fragment_68_seconds_is_marked_partial(self):
        self.assertTrue(collector.asr_output_needs_review(
            "中海开发商好爱惜自己嘅口碑就连", 68,
        ))

    def test_dense_37_second_transcript_is_complete(self):
        self.assertFalse(collector.asr_output_needs_review("完整口播" * 30, 37))

    def test_short_video_is_not_density_rejected(self):
        self.assertFalse(collector.asr_output_needs_review("短视频真实口播内容", 12))

    def test_truncated_21_second_transcript_is_retried(self):
        self.assertTrue(collector.asr_output_needs_review(
            "中海金沙馨园一期广", 21,
            config={
                "client_asr_review_min_duration_seconds": 10,
                "client_asr_min_chars_per_second": 0.65,
            },
        ))

    def test_exact_asr_child_does_not_age_unrelated_pending_video(self):
        checkpoint = {
            "status": "retry_pending",
            "title": "可稳定定位的视频",
        }
        self.assertFalse(collector.should_age_missing_retry(
            "fingerprint-other", checkpoint, set(),
            asr_backfill_mode=True,
            retry_fingerprint="fingerprint-owned",
        ))
        self.assertTrue(collector.should_age_missing_retry(
            "fingerprint-owned", checkpoint, set(),
            asr_backfill_mode=True,
            retry_fingerprint="fingerprint-owned",
        ))

    def test_identityless_placeholder_never_consumes_retry_budget(self):
        checkpoint = {"status": "retry_pending", "row": None, "title": ""}
        self.assertFalse(collector.retry_checkpoint_has_identity(checkpoint))
        self.assertFalse(collector.should_age_missing_retry(
            "fingerprint-empty", checkpoint, set(),
            asr_backfill_mode=False,
            retry_fingerprint=None,
        ))

    def test_playback_coverage_requires_near_end_progress(self):
        self.assertFalse(collector.playback_capture_is_complete(
            {"maxElapsed": 4, "observedTotal": 227}, 227, 4,
        ))
        self.assertTrue(collector.playback_capture_is_complete(
            {"maxElapsed": 224, "observedTotal": 227}, 227, 4,
        ))
        self.assertFalse(collector.playback_capture_is_complete(
            {"maxElapsed": 14, "observedTotal": 14}, 169, 4,
        ))
        self.assertTrue(collector.playback_capture_is_complete(
            # The original 81-second video reached its end before autoplay
            # switched the final sampled clock to the next 8-second item.
            {"maxElapsed": 81, "observedTotal": 8}, 81, 4,
        ))
        self.assertIsNone(collector.playback_capture_is_complete(
            {"maxElapsed": None, "observedTotal": None}, 227, 4,
        ))

    def test_audio_active_only_at_start_requires_recapture(self):
        self.assertTrue(collector.recorder_audio_coverage_is_suspicious({
            "activeSecondCount": 3,
            "lastActiveSecond": 4,
            "silentTailSeconds": 71,
        }, 68))
        self.assertFalse(collector.recorder_audio_coverage_is_suspicious({
            "activeSecondCount": 60,
            "lastActiveSecond": 67,
            "silentTailSeconds": 8,
        }, 68))

    def test_progress_parser_supports_hour_and_minute_clocks(self):
        records = [
            ("0:04 / 3:47", "Text", ""),
            ("1:02:03 / 1:05:00", "Text", ""),
        ]
        self.assertEqual(
            collector.parse_video_progress_records(records, 227), (4, 227)
        )

    def test_detail_player_total_overrides_search_card_countdown(self):
        records = [("00:08 / 06:05", "Text", "time")]
        with patch.object(collector, "read_active_video_progress", return_value=(8, 365)):
            self.assertEqual(
                collector.resolve_video_detail_duration(object(), records, 56),
                365,
            )

    def test_detail_duration_falls_back_to_card_when_clock_is_missing(self):
        with patch.object(collector, "read_active_video_progress", return_value=None):
            self.assertEqual(
                collector.resolve_video_detail_duration(object(), [], 56),
                56,
            )

    def test_nonempty_short_vad_result_still_runs_no_vad(self):
        class SparseThenCompleteModel:
            def __init__(self):
                self.calls = []

            def transcribe(self, _path, **options):
                self.calls.append(options)
                if options.get("vad_filter"):
                    return iter([Segment("只有十五个字的残缺内容")]), Info(4.0)
                return iter([Segment(
                    "今天带大家看看中海住宅项目，先从园林入口开始，再介绍社区会所、"
                    "户型设计、采光通风和精装修细节。南向客厅连接景观阳台，厨房与餐厅"
                    "动线清晰，主卧套房包含独立衣帽间和卫生间，儿童房也预留了收纳空间。"
                )]), Info(68.0)

        model = SparseThenCompleteModel()
        text, _info, _segments, fallback, _audits = collector.transcribe_audio_with_recovery(
            model, Path("missing.wav"), {}, "中海住宅", 68,
        )
        self.assertGreater(len(text), 80)
        self.assertTrue(fallback)
        self.assertEqual(len(model.calls), 2)

    def test_chunk_recovery_replaces_still_sparse_full_passes(self):
        class AlwaysSparseModel:
            def transcribe(self, _path, **_options):
                return iter([Segment("残缺片段")]), Info(3.0)

        recovered = "分段恢复后的完整口播" * 20
        with patch.object(
            collector,
            "transcribe_sparse_audio_in_chunks",
            return_value=(recovered, {"pass": "chunked_recovery", "quality": {}}, Info(60), []),
        ) as chunked:
            text, _info, _segments, fallback, audits = collector.transcribe_audio_with_recovery(
                AlwaysSparseModel(), Path("missing.wav"), {}, "中海住宅", 68,
            )
        self.assertEqual(text, recovered)
        self.assertTrue(fallback)
        self.assertEqual(chunked.call_count, 1)
        self.assertEqual(audits[-1]["pass"], "chunked_recovery")

    def test_chunk_merge_removes_boundary_overlap(self):
        self.assertEqual(
            collector.merge_asr_chunks([
                "今天介绍中海住宅产品体系和园林景观",
                "产品体系和园林景观接下来看看户型设计",
            ]),
            "今天介绍中海住宅产品体系和园林景观接下来看看户型设计",
        )

    def test_sparse_real_speech_is_warning_not_rejected(self):
        text, audit = collector.assess_asr_text_quality(
            "真实口播内容",
            capture_seconds=60,
            speech_seconds=2.0,
        )
        self.assertEqual(text, "真实口播内容")
        self.assertTrue(audit["low_speech_density_warning"])

    def test_raw_subtitle_artifacts_cannot_be_cleaned_into_success(self):
        for raw in (
            '人大附近中海住宅，中文字幕志愿者刘娅中文字幕组，近中海环宇城',
            '真实口播，请不吝点赞订阅转发打赏支持明镜与点点栏目',
            '真实口播，AMARA.ORG',
            '真实口播，字幕 BY 索兰娅',
        ):
            with self.subTest(raw=raw):
                text, audit = collector.assess_asr_text_quality(raw, capture_seconds=69, speech_seconds=40)
                self.assertIsNone(text)
                self.assertFalse(audit['accepted'])
                self.assertEqual(audit['reason'], 'known_whisper_hallucination')
                with self.assertRaises(collector.AsrQualityRejectedError):
                    collector.require_trustworthy_asr_result(text, [{'quality': audit}])
        for raw in ('字幕展示的是户型尺寸，客厅面宽六米', '欢迎观看样板间，感谢大家支持'):
            text, audit = collector.assess_asr_text_quality(raw, capture_seconds=10, speech_seconds=5)
            self.assertEqual(text, raw)
            self.assertTrue(audit['accepted'])

    def test_spoken_caption_is_not_rejected_as_prompt_echo(self):
        text, audit = collector.assess_asr_text_quality(
            "华润臻澐值得买吗",
            prompt_context="华润臻澐值得买吗",
            capture_seconds=10,
            speech_seconds=3.0,
        )
        self.assertEqual(text, "华润臻澐值得买吗")
        self.assertFalse(audit["prompt_echo"])

    def test_rejected_vad_pass_retries_without_vad(self):
        model = FakeModel()
        text, _info, _segments, fallback, audits = collector.transcribe_audio_with_recovery(
            model,
            Path("sample.wav"),
            {"client_asr_beam_size": 8, "client_asr_vad_threshold": 0.35},
            "北京臻澐",
            20,
        )
        self.assertEqual(text, "开头三秒也应完整保留，随后继续介绍项目。")
        self.assertTrue(fallback)
        self.assertEqual(len(model.calls), 2)
        self.assertTrue(model.calls[0]["vad_filter"])
        self.assertFalse(model.calls[1]["vad_filter"])
        self.assertEqual(audits[0]["quality"]["reason"], "known_whisper_hallucination")

    def test_recorder_ready_handshake(self):
        payload = {"event": "loopback_recorder_ready", "ready": True, "readyEndpoints": 2}
        process = FakeProcess(json.dumps(payload, ensure_ascii=False) + "\n")
        self.assertEqual(
            collector.wait_for_loopback_recorder_ready(process, 1)["readyEndpoints"],
            2,
        )

    def test_wechat_audio_session_prefers_renderer_process(self):
        audit = {"sessions": [
            {"pid": 100, "process": "Weixin.exe"},
            {"pid": 3008, "process": "WeChatAppEx.exe"},
        ]}
        self.assertEqual(
            collector.select_wechat_audio_process_id(audit),
            3008,
        )

    def test_process_loopback_is_selected_for_wechat_audio_session(self):
        command, source, process_id = collector.loopback_recorder_command(
            Path("loopback-recorder.py"), 3, 16000, Path("sample.wav"),
            {"sessions": [{"pid": 3008, "process": "WeChatAppEx.exe"}]},
        )
        self.assertEqual(source, "windows_process_loopback")
        self.assertEqual(process_id, 3008)
        self.assertEqual(command[-2:], ["--process-id", "3008"])

    def test_verified_preflight_process_overrides_new_session_guess(self):
        command, source, process_id = collector.loopback_recorder_command(
            Path("loopback-recorder.py"), 81, 16000, Path("sample.wav"),
            {"sessions": [{"pid": 39376, "process": "WeChatAppEx.exe"}]},
            27868,
            prefer_explicit_process_id=True,
        )
        self.assertEqual(source, "windows_process_loopback")
        self.assertEqual(process_id, 27868)
        self.assertEqual(command[-2:], ["--process-id", "27868"])

    def test_endpoint_loopback_remains_fallback_without_audio_session(self):
        command, source, process_id = collector.loopback_recorder_command(
            Path("loopback-recorder.py"), 3, 16000, Path("sample.wav"),
            {"sessions": []},
        )
        self.assertEqual(source, "windows_wasapi_loopback")
        self.assertIsNone(process_id)
        self.assertNotIn("--process-id", command)

    def test_video_surface_pid_keeps_process_loopback_when_audio_session_is_paused(self):
        with patch.object(collector, "active_video_root", side_effect=RuntimeError("no child root")):
            self.assertEqual(collector.video_surface_process_id(FakeProcessSurface()), 3008)
        command, source, process_id = collector.loopback_recorder_command(
            Path("loopback-recorder.py"), 3, 16000, Path("sample.wav"),
            {"sessions": []}, 3008,
        )
        self.assertEqual(source, "windows_process_loopback")
        self.assertEqual(process_id, 3008)
        self.assertEqual(command[-2:], ["--process-id", "3008"])

    def test_recorder_startup_failure_reports_child_stderr(self):
        class FailedProcess:
            stdout = io.StringIO("")
            stderr = io.StringIO("ModuleNotFoundError: No module named 'soundcard'")

            @staticmethod
            def poll():
                return 1

        with self.assertRaisesRegex(RuntimeError, "soundcard"):
            collector.wait_for_loopback_recorder_ready(FailedProcess(), 1)

    def test_closed_sound_state_is_not_parsed_as_article_title(self):
        parsed = collector.parse_video_card_text(
            "00:44 关闭声音 #唐山中海和园#唐山四代宅 唐山蓝鲸讲房小栾 10分钟前"
        )
        self.assertIsNone(parsed["title"])
        self.assertEqual(parsed["author_name"], "唐山蓝鲸讲房小栾")
        self.assertEqual(parsed["tags"], "唐山中海和园,唐山四代宅")

    def test_visible_login_window_blocks_duplicate_client_launch(self):
        with patch.object(
            collector, "_wechat_login_windows", return_value=[object(), object()],
        ), patch.object(
            collector, "_wechat_hidden_main_candidates", return_value=[],
        ), patch.object(collector.subprocess, "Popen") as launch:
            self.assertFalse(collector.wake_wechat_main_window())
        launch.assert_not_called()

    def test_copy_link_does_not_unconditionally_escape_embedded_detail(self):
        source = SOURCE.read_text(encoding="utf-8")
        function = source[
            source.index("def copy_article_link_from_menu("):
            source.index("def parse_visible_comments(")
        ]
        self.assertIn("if open_menu_items:", function)
        self.assertNotIn(
            'web.set_focus()\n    keyboard.send_keys("{ESC}"', function,
        )

    def test_head_prefix_merge_restores_missing_opening_words(self):
        self.assertEqual(
            collector.merge_asr_head_prefix(
                "昨天说了万橡府建发海宴",
                "说了万橡府建发海宴三个楼盘的优点",
            ),
            "昨天说了万橡府建发海宴三个楼盘的优点",
        )

    def test_non_overlapping_head_is_not_speculatively_prepended(self):
        self.assertEqual(
            collector.merge_asr_head_prefix(
                "昨天先看项目区位",
                "接下来介绍户型和园林",
            ),
            "接下来介绍户型和园林",
        )

    def test_real_head_homophones_do_not_duplicate_opening(self):
        head = "东海大镜的140方的实力版方，这个互形呢我们现在18楼，它的景观是非常棒的，前面是无"
        full = "东海大镜的140方的实力板方，这个户型呢我们现在在18楼，它的景观是非常棒的，前面是无遮挡的，因为它是国家的实力公园"
        self.assertEqual(collector.merge_asr_head_prefix(head, full), full)

    def test_real_opening_mismatch_is_not_prepended(self):
        head = "中海大静的148的实力版发，这个互联的我们现在18楼，它的景观是非常棒的前面是"
        full = "中海大镜的140方的实力板方，这个户型呢我们现在18楼，它的景观是非常棒的，前面是无遮挡的，因为它是国家的实力公园"
        self.assertEqual(collector.merge_asr_head_prefix(head, full), full)

    def test_genuine_later_repetition_is_retained(self):
        full = "今天介绍这个项目，交通便利，今天介绍这个项目的厨房"
        self.assertEqual(collector.merge_asr_head_prefix("今天介绍这个项目", full), full)

    def test_head_prefix_punctuation_difference_is_not_duplicated(self):
        full = "华润臻澐三个楼盘的缺点，今天咱们必须把这个优点给读"
        self.assertEqual(
            collector.merge_asr_head_prefix(
                "华润臻澐,三个楼盘的缺点，今天咱们必须把",
                full,
            ),
            full,
        )

    def test_head_prefix_arabic_ten_matches_spoken_chinese_ten(self):
        full = "步行十分钟到清华大学,这是海淀区最稀缺的四代宅"
        self.assertEqual(
            collector.merge_asr_head_prefix(
                "步行10分钟到清华大学,这是海淀区",
                full,
            ),
            full,
        )

    def test_head_prefix_simplified_traditional_difference_is_not_duplicated(self):
        self.assertEqual(
            collector.merge_asr_head_prefix(
                "昨天说了万橡府建发海宴华润臻澐",
                "昨天說了萬橡府建發海宴",
            ),
            "昨天说了万橡府建发海宴华润臻澐",
        )

    def test_boilerplate_is_removed_from_mixed_real_text(self):
        self.assertEqual(
            collector.clean_asr_text(
                "请不吝点赞订阅转发打赏支持明镜与点点栏目，真实口播内容"
            ),
            "真实口播内容",
        )

    def test_music_outro_hallucination_is_removed(self):
        self.assertEqual(
            collector.clean_asr_text(
                "中海开发商好爱惜自己嘅口碑，就连，多谢这边的观看欢迎订阅点赞转发等以后再继续订阅"
            ),
            "中海开发商好爱惜自己嘅口碑，就连",
        )

    def test_adjacent_repeated_clause_block_is_collapsed(self):
        self.assertEqual(
            collector.clean_asr_text(
                "中海开发商好爱惜自己的口碑，就连，中海开发商好爱惜自己的口碑，就连"
            ),
            "中海开发商好爱惜自己的口碑，就连",
        )

    def test_two_detached_windows_are_selected_by_explicit_role(self):
        search = FakeDetachedWindow(101, "中海住宅 - 搜一搜")
        detail = FakeDetachedWindow(202, "视频号")
        with patch.object(
            collector, "web_windows", return_value=[search, detail]
        ), patch.object(
            collector.ctypes.windll.user32,
            "GetForegroundWindow",
            return_value=202,
        ):
            selected = collector.try_get_search_window()
            selected_detail = collector.try_get_video_detail_window()
        self.assertIs(selected, search)
        self.assertTrue(search.focused)
        self.assertIs(selected_detail, detail)
        self.assertTrue(detail.focused)

    def test_search_existence_probe_does_not_steal_focus(self):
        search = FakeDetachedWindow(101, "中海住宅 - 搜一搜")
        detail = FakeDetachedWindow(202, "视频号")
        with patch.object(collector, "web_windows", return_value=[search, detail]):
            self.assertTrue(collector.has_search_window())
        self.assertFalse(search.focused)
        self.assertFalse(detail.focused)

    def test_missing_detail_probe_does_not_wake_or_focus_wechat(self):
        search = FakeDetachedWindow(101, "中海住宅 - 搜一搜")
        with patch.object(
            collector, "web_windows", return_value=[search]
        ), patch.object(
            collector, "_wechat_main_window_candidates", return_value=[]
        ), patch.object(
            collector, "get_wechat_window", side_effect=AssertionError("must not focus")
        ):
            self.assertFalse(collector.has_video_detail_window())
        self.assertFalse(search.focused)

    def test_multiple_stale_players_are_detected_for_cleanup(self):
        first = FakeDetachedWindow(201, "视频号")
        second = FakeDetachedWindow(202, "视频号")
        with patch.object(collector, "web_windows", return_value=[first, second]):
            self.assertTrue(collector.has_video_detail_window())
        self.assertFalse(first.focused)
        self.assertFalse(second.focused)

    def test_unknown_sibling_is_treated_as_search_during_hydration(self):
        unknown_search = FakeDetachedWindow(101, "")
        detail = FakeDetachedWindow(202, "视频号")
        with patch.object(
            collector, "web_windows", return_value=[unknown_search, detail]
        ):
            selected = collector.try_get_search_results_window(focus=False)
        self.assertIs(selected, unknown_search)

    def test_repeated_two_window_poll_logs_topology_once(self):
        search = FakeDetachedWindow(101, "中海住宅 - 搜一搜")
        detail = FakeDetachedWindow(202, "视频号")
        collector.LAST_MULTI_WINDOW_SIGNATURE = None
        output = io.StringIO()
        with patch.object(
            collector, "web_windows", return_value=[search, detail]
        ), patch("sys.stdout", output):
            for _index in range(1200):
                selected = collector.try_get_search_results_window(focus=False)
                self.assertIs(selected, search)
        self.assertEqual(output.getvalue().count("multiple_wechat_web_windows_resolved"), 1)
        self.assertFalse(search.focused)
        self.assertFalse(detail.focused)

    def test_return_to_results_closes_separate_video_player_window(self):
        search = FakeDetachedWindow(101, "中海住宅 - 搜一搜")
        detail = FakeDetachedWindow(202, "视频号")

        def current_windows():
            return [item for item in (search, detail) if not item.closed]

        collector.SEARCH_LAYOUT = "detached"
        with patch.object(
            collector, "web_windows", side_effect=current_windows
        ), patch.object(collector.time, "sleep", return_value=None):
            collector.return_to_search_results()
        self.assertTrue(detail.closed)
        self.assertFalse(search.closed)

    def test_keyword_cleanup_closes_standalone_stale_player(self):
        detail = FakeDetachedWindow(202, "视频号")

        def current_windows():
            return [] if detail.closed else [detail]

        with patch.object(
            collector, "web_windows", side_effect=current_windows
        ), patch.object(collector.time, "sleep", return_value=None):
            closed = collector.cleanup_stale_video_windows(
                reason="test_keyword_start", require_search_peer=False,
            )
        self.assertEqual(closed, 1)
        self.assertTrue(detail.closed)

    def test_stubborn_video_window_fails_after_bounded_close_attempts(self):
        search = FakeDetachedWindow(101, "中海住宅 - 搜一搜")
        detail = FakeDetachedWindow(202, "视频号")
        detail.close = lambda: None
        with patch.object(
            collector, "web_windows", return_value=[search, detail]
        ), patch.object(
            collector.time, "time", side_effect=[0.0, 10.0, 20.0, 30.0]
        ), patch.object(collector.time, "sleep", return_value=None):
            with self.assertRaises(collector.SearchWindowUnavailableError):
                collector.cleanup_stale_video_windows(
                    reason="test_close_failure", require_search_peer=True,
                )

    def test_stacked_video_tabs_are_closed_until_search_tab_is_visible(self):
        surface = FakeDetachedWindow(202, "视频号")
        close_count = 0

        def close_active_tab(_keys, **_kwargs):
            nonlocal close_count
            close_count += 1
            surface.document_name = "搜一搜" if close_count >= 2 else "视频号"

        with patch.object(
            collector, "web_windows", return_value=[surface]
        ), patch.object(
            collector.keyboard, "send_keys", side_effect=close_active_tab
        ), patch.object(collector.time, "sleep", return_value=None):
            closed = collector.close_stacked_video_tabs_until_search_results(surface)
        self.assertEqual(closed, 2)
        self.assertEqual(close_count, 2)
        self.assertEqual(collector.detached_web_window_role(surface), "search_results")

    def test_stacked_video_tab_cleanup_is_bounded(self):
        surface = FakeDetachedWindow(202, "视频号")
        with patch.object(
            collector, "web_windows", return_value=[surface]
        ), patch.object(
            collector.keyboard, "send_keys", return_value=None
        ), patch.object(collector.time, "sleep", return_value=None):
            with self.assertRaises(collector.SearchWindowUnavailableError):
                collector.close_stacked_video_tabs_until_search_results(
                    surface, max_tabs=2,
                )

    def test_finished_scan_remains_complete_when_video_retry_is_deferred(self):
        self.assertEqual(
            collector.status_with_deferred_video_retries("complete_cutoff", 2),
            "complete_cutoff_with_deferred_retry",
        )
        self.assertEqual(
            collector.status_with_deferred_video_retries("complete_exhausted", 1),
            "complete_exhausted_with_deferred_retry",
        )

    def test_unfinished_scan_with_retry_remains_partial(self):
        self.assertEqual(
            collector.status_with_deferred_video_retries("running", 1),
            "partial_retry_pending",
        )

    def test_every_first_explicit_empty_stays_partial_for_later_resume(self):
        self.assertEqual(
            collector.explicit_empty_status(1),
            "partial_inconsistent_empty",
        )
        self.assertEqual(
            collector.explicit_empty_status(0),
            "partial_empty_unverified",
        )

    def test_redis_retry_matches_same_card_when_autoplay_duration_drifts(self):
        checkpoint = {
            "row": {
                "title": '中国の"畳める家"、海外で人気急上昇！',
                "author_name": "上海japion",
                "video_duration": 38,
            }
        }
        live_card = {
            "title": '中国の"畳める家"、海外で人気急上昇！',
            "author_name": "上海japion",
            "duration_seconds": 27,
        }
        self.assertTrue(
            collector.retry_checkpoint_matches_card(checkpoint, live_card)
        )
        live_card["author_name"] = "另一个作者"
        self.assertFalse(
            collector.retry_checkpoint_matches_card(checkpoint, live_card)
        )

    def test_redis_retry_accepts_truncated_title_only_with_same_author(self):
        checkpoint = {
            "title": "中海学仕里业主开放日，十月份交房在即，曲美整家征集全户型样板间",
            "author_name": "曲美家居呼和浩特",
        }
        card = {
            "title": "中海学仕里业主开放日，十月份交房在即",
            "author_name": "曲美家居呼和浩特",
        }
        self.assertTrue(collector.retry_checkpoint_matches_card(checkpoint, card))
        card["author_name"] = "其他作者"
        self.assertFalse(collector.retry_checkpoint_matches_card(checkpoint, card))

    def test_resume_canonicalizes_unique_countdown_drift(self):
        checkpoints = {
            "dur38": {
                "row": {
                    "title": "倒计时会变化的视频",
                    "author_name": "测试作者",
                    "video_duration": 38,
                }
            }
        }
        card = {
            "title": "倒计时会变化的视频",
            "author_name": "测试作者",
            "duration_seconds": 24,
        }
        self.assertEqual(
            collector.unique_checkpoint_for_stable_card_identity(checkpoints, card),
            ("dur38", checkpoints["dur38"]),
        )

    def test_resume_does_not_canonicalize_ambiguous_same_author_and_title(self):
        checkpoints = {
            "first": {"row": {"title": "相同标题", "author_name": "同一作者"}},
            "second": {"row": {"title": "相同标题", "author_name": "同一作者"}},
        }
        card = {"title": "相同标题", "author_name": "同一作者"}
        self.assertIsNone(
            collector.unique_checkpoint_for_stable_card_identity(checkpoints, card)
        )

    def test_resume_never_canonicalizes_same_title_from_another_author(self):
        checkpoints = {
            "first": {"row": {"title": "相同标题", "author_name": "作者甲"}}
        }
        card = {"title": "相同标题", "author_name": "作者乙"}
        self.assertIsNone(
            collector.unique_checkpoint_for_stable_card_identity(checkpoints, card)
        )

    def test_exact_retry_scan_is_bounded_but_honours_deep_original_index(self):
        config = {
            "asr_retry_min_scan_results": 36,
            "asr_retry_scan_ahead_results": 36,
            "asr_retry_hard_cap_results": 240,
        }
        with patch.dict(
            collector.os.environ, {"WECHAT_REDIS_VIDEO_RESULT_INDEX": ""}, clear=False,
        ):
            self.assertEqual(collector.redis_retry_card_scan_limit(config), 240)
        with patch.dict(
            collector.os.environ, {"WECHAT_REDIS_VIDEO_RESULT_INDEX": "120"}, clear=False,
        ):
            self.assertEqual(collector.redis_retry_card_scan_limit(config), 157)
        with patch.dict(
            collector.os.environ, {"WECHAT_REDIS_VIDEO_RESULT_INDEX": "999"}, clear=False,
        ):
            self.assertEqual(collector.redis_retry_card_scan_limit(config), 240)

    def test_redis_retry_can_match_pre_detail_identity(self):
        checkpoint = {
            "title": "尚未打开详情的视频",
            "author_name": "中海官方",
            "row": None,
        }
        live_card = {
            "title": "尚未打开详情的视频",
            "author_name": "中海官方",
            "duration_seconds": 18,
        }
        self.assertTrue(collector.retry_checkpoint_matches_card(checkpoint, live_card))


if __name__ == "__main__":
    unittest.main()
