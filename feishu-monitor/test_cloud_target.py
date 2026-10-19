import unittest
from unittest.mock import patch
import cloud_log


class CloudTargetTests(unittest.TestCase):
    def test_unconfigured_example_fails_before_network(self):
        with patch.object(cloud_log, 'TARGET_URL', 'https://example.feishu.cn/wiki/EXAMPLE_LOG_DOCUMENT'), patch.object(cloud_log, 'NODE', 'EXAMPLE_LOG_DOCUMENT'):
            with self.assertRaisesRegex(cloud_log.SyncError, 'cloud_target_missing_or_invalid'):
                cloud_log.validate_cloud_target()

    def test_explicit_feishu_wiki_target_is_accepted(self):
        with patch.object(cloud_log, 'TARGET_URL', 'https://fixture.feishu.cn/wiki/FixtureDocument'), patch.object(cloud_log, 'NODE', 'FixtureDocument'):
            cloud_log.validate_cloud_target()

    def test_untrusted_url_userinfo_query_and_wrong_resource_fail(self):
        for url in ['http://fixture.feishu.cn/wiki/test', 'https://evil.example/wiki/test',
                    'https://user:secret@fixture.feishu.cn/wiki/test',
                    'https://fixture.feishu.cn/wiki/test?token=hidden',
                    'https://fixture.feishu.cn/docx/test']:
            with self.subTest(url=url), patch.object(cloud_log, 'TARGET_URL', url), patch.object(cloud_log, 'NODE', 'test'):
                with self.assertRaises(cloud_log.SyncError):
                    cloud_log.validate_cloud_target()


if __name__ == '__main__':
    unittest.main()
