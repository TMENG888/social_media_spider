import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
import channels_pc_collector as collector
from search_scan_proof import SearchEndTracker


class Rect:
    def __init__(self, top=0, bottom=1000):
        self.top, self.bottom, self.left, self.right = top, bottom, 0, 900

    def width(self):
        return self.right - self.left

    def height(self):
        return self.bottom - self.top


class Control:
    def __init__(self, name, kind, parent=None, rect=None, class_name=''):
        self.name, self.owner, self.rect = name, parent, rect or Rect()
        self.element_info = SimpleNamespace(control_type=kind, class_name=class_name)

    def window_text(self):
        return self.name

    def parent(self):
        return self.owner

    def rectangle(self):
        return self.rect

    def is_visible(self):
        return True


def fixture(percent=100., marker_parent='document', marker='没有更多了', marker_kind='Text'):
    keyword = '原检索词'
    document = Control(keyword + ' - 视频 - 搜一搜', 'Document')
    document.iface_scroll = SimpleNamespace(CurrentVerticallyScrollable=True, CurrentVerticalScrollPercent=percent)
    cards = [Control('视频一', 'ListItem', document, Rect(100, 200), 'rich-media'),
             Control('视频二', 'ListItem', document, Rect(850, 950), 'rich-media')]
    text = Control(marker, marker_kind, cards[-1] if marker_parent == 'card' else document, Rect(960, 990))
    document.descendants = lambda control_type=None: cards if control_type == 'ListItem' else cards + [text] if control_type is None else [text] if control_type == 'Text' else []
    surface = SimpleNamespace(descendants=lambda control_type=None: [document])
    return keyword, surface


class SearchSurfaceSnapshotTests(unittest.TestCase):
    def test_actual_reader_captures_scroll_pattern_without_count_based_inference(self):
        keyword, surface = fixture(marker_parent='card')
        origin = collector.search_scan_surface_snapshot(surface, keyword)
        self.assertTrue(origin['contextValid']);self.assertEqual(origin['scrollPercent'], 100.)
        self.assertIsNone(origin['terminalText'])
        # Same cards, but a scroller at 40% cannot become EOF after any count of
        # identical samples. The true origin and bottom are separate evidence.
        origin['scrollPercent'] = 0.
        tracker = SearchEndTracker(keyword, origin, True)
        for cycle in range(1, 5):
            _, middle = fixture(percent=40, marker_parent='card')
            sample = collector.search_scan_surface_snapshot(middle, keyword, scanned_count=2, surface_generation=cycle)
            self.assertFalse(tracker.observe(sample)['ok'])

    def test_reader_scopes_terminal_to_visible_document_below_cards(self):
        keyword, surface = fixture(percent=None)
        sample = collector.search_scan_surface_snapshot(surface, keyword)
        self.assertEqual(sample['terminalText'], '没有更多了')
        self.assertTrue(sample['terminalOutsideCards']);self.assertTrue(sample['terminalBelowCards'])
        self.assertTrue(sample['lastCardInViewport'])
        wrong = collector.search_scan_surface_snapshot(surface, '其他检索词')
        self.assertFalse(wrong['contextValid']);self.assertIsNone(wrong['terminalText'])

    def test_reader_exposes_page_failure_instead_of_accepting_cached_cards(self):
        keyword, surface = fixture(marker='网络异常，请重试')
        sample = collector.search_scan_surface_snapshot(surface, keyword)
        self.assertTrue(sample['loadFailed'])

    def test_loading_progress_without_text_is_not_missed(self):
        keyword, surface = fixture(marker='', marker_kind='ProgressBar')
        self.assertTrue(collector.search_scan_surface_snapshot(surface, keyword)['loading'])
