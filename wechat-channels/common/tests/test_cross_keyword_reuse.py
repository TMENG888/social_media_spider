import copy
import json
import sys
import tempfile
import unittest
from contextlib import closing
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
import channels_pc_collector as c


class CrossKeywordReuseTests(unittest.TestCase):
    def source(self):
        row = c.ResultRow(project='test', keyword='source', title='真实来源标题',
            url='https://weixin.qq.com/sph/Exact1234', author_name='真实作者',
            published_at='2026-06-01 12:00:00', video_duration=20,
            video_content='真实来源口播介绍项目的园林设计和住宅户型布局，客厅开间六米，餐客厅一体。',
            like_count=1, comment_count=1, favorite_count=0, share_count=0)
        comments = [{'comment_id':'source-comment', 'content':'真实评论', 'user_name':'用户'}]
        return {'status':'completed','article_key':c.article_key_for_row(row),
                'keyword':'source','project':'test','row':asdict(row),
                'asr_status':'completed','comments':comments,
                'field_completeness':c.video_field_completeness(row, comments, asr_status='completed')}

    def ready(self, cp, **overrides):
        args = dict(project='test',article_key=self.source()['article_key'],
                    url=self.source()['row']['url'],author='真实作者',duration=20,
                    cutoff=datetime(2026,1,1),collect_comments=True)
        args.update(overrides)
        return c.reusable_cross_keyword_checkpoint(cp, **args)

    def test_only_exact_usable_source_can_be_reused(self):
        self.assertTrue(self.ready(self.source()))
        for status in ('completed_metadata','dead_letter','retry_pending','skipped_unresolved'):
            cp=self.source();cp['status']=status
            self.assertFalse(self.ready(cp), status)
        for overrides in ({'project':'other'},{'url':'https://weixin.qq.com/sph/Other1234'},
                          {'url':'https://example.invalid/sph/Exact1234'},
                          {'author':'其他作者'},{'duration':40},{'duration':float('nan')}):
            self.assertFalse(self.ready(self.source(),**overrides), overrides)

    def test_bad_source_does_not_skip_real_collection(self):
        for field,value in [('video_content','中文字幕志愿者刘娅中文字幕组'),
                            ('published_at','2025-06-01 12:00:00'),('published_at',None),
                            ('author_name',None),('title',None),('video_duration',float('nan')),
                            ('video_content','过短')]:
            cp=self.source();cp['row'][field]=value
            self.assertFalse(self.ready(cp), field)
        cp=self.source();cp['comments']=[]
        self.assertFalse(self.ready(cp))
        self.assertTrue(self.ready(cp,collect_comments=False))
        cp=self.source();cp['field_completeness']['duration']=False
        self.assertFalse(self.ready(cp))
        cp=self.source();cp['asr_status']='partial_review'
        self.assertFalse(self.ready(cp))
        cp=self.source();cp['subtitle_review_required']=True
        self.assertFalse(self.ready(cp))
        cp=self.source();cp['asr_status']='no_content'
        self.assertFalse(self.ready(cp))

    def test_reuse_persists_receiving_keyword_and_preserves_attempts_and_evidence(self):
        with tempfile.TemporaryDirectory() as folder, closing(c.init_state(Path(folder)/'state.sqlite')) as db:
            source=self.source();retained=copy.deepcopy(source)
            c.save_row(db,c.ResultRow(**source['row']))
            old_row=c.ResultRow(**{**source['row'],'keyword':'receiving','video_content':'旧候选正文，完整留证'})
            c.save_row(db,old_row)
            c.save_comments(db,old_row,[{'comment_id':'source-comment','content':'旧评论正文留证'}])
            before=c.upsert_video_checkpoint(db,keyword='receiving',project='test',fingerprint='fp',
                status='retry_pending',retry_count=2,last_error='old failure',row=old_row)
            cursor=db.execute("SELECT * FROM video_checkpoint WHERE keyword='receiving' AND fingerprint='fp'")
            previous_record=dict(zip((item[0] for item in cursor.description),cursor.fetchone()))
            remote=MagicMock()
            result=c.persist_cross_keyword_reuse(db,checkpoint=source,keyword='receiving',
                project='test',fingerprint='fp',result_index=4,cutoff=datetime(2026,1,1),
                collect_comments=True,remote_store=remote)
            self.assertEqual(source,retained)
            self.assertEqual(result['status'],'completed')
            self.assertEqual(result['retry_count'],2)
            self.assertEqual(result['row']['keyword'],'receiving')
            self.assertEqual(result['article_key'],source['article_key'])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM captured_article').fetchone()[0],2)
            self.assertEqual(db.execute("SELECT content FROM captured_comment WHERE keyword='receiving'").fetchone()[0],'真实评论')
            audit=db.execute('SELECT source_checkpoint,previous_checkpoint,previous_article,previous_comments FROM cross_keyword_reuse_audit').fetchone()
            self.assertEqual(json.loads(audit[0]),source)
            self.assertEqual(json.loads(audit[1]),previous_record)
            self.assertEqual(json.loads(audit[2])['video_content'],'旧候选正文，完整留证')
            self.assertEqual(json.loads(audit[3])[0]['content'],'旧评论正文留证')
            remote.put.assert_called_once()
            remote.put_global.assert_called_once()

    def test_reuse_cannot_revive_explicit_skip_or_overwrite_another_identity(self):
        for skipped in (True,False):
            with self.subTest(skipped=skipped),tempfile.TemporaryDirectory() as folder,closing(c.init_state(Path(folder)/'state.sqlite')) as db:
                other=c.ResultRow(project='test',keyword='receiving',title='其他视频',
                                  url='https://weixin.qq.com/sph/Other1234',author_name='其他作者')
                c.upsert_video_checkpoint(db,keyword='receiving',project='test',fingerprint='fp',
                    status='skipped_unresolved' if skipped else 'retry_pending',retry_count=3,row=other)
                before=c.load_video_checkpoints(db,'receiving')
                with self.assertRaisesRegex(RuntimeError,'CROSS_KEYWORD_REUSE_'):
                    c.persist_cross_keyword_reuse(db,checkpoint=self.source(),keyword='receiving',
                        project='test',fingerprint='fp',result_index=4,cutoff=datetime(2026,1,1))
                self.assertEqual(c.load_video_checkpoints(db,'receiving'),before)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM captured_article').fetchone()[0],0)


if __name__ == '__main__':
    unittest.main()
