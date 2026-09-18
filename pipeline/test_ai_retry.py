import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_retry import next_retry, pending_tasks, reader_content, restore_state
from curate import digest, VERSION
from collect import collect, SOURCES


@patch.dict(os.environ, {'TEST_KEY': 'fixture'}, clear=True)
class RetryTests(unittest.TestCase):
    def setUp(self):
        self.item = {'id': 1, 'title': 'Company update', 'excerpt': 'New trial results.', 'language': 'en'}
        self.snapshot = {'items': [self.item], 'updated_at': 900,
                         'briefing': {'format_version': 2, 'generated_at': 950, 'router_state': {}}}
        self.config = {'strategy': 'failover', 'max_input_articles': 20, 'summary_interval_hours': 6,
                       'providers': [{'id': name, 'enabled': True, 'key_env': 'TEST_KEY',
                                      'models': [{'id': 'model', 'enabled': True, 'free_tier': 'free',
                                                  'tasks': ['news_translation', 'news_curation', 'news_summary']} ]}
                                     for name in ('amd', 'sensenova')]}

    def test_wakes_at_earliest_model_cooldown_not_next_rss_run(self):
        self.snapshot['briefing']['router_state']['cooldowns'] = {'amd/model': 1900, 'supplier:sensenova': 4600}
        self.assertEqual(next_retry(self.snapshot, self.config, 1000), 1900)
        self.assertEqual(next_retry(self.snapshot, self.config, 1900), 2020)

    def test_no_more_work_stops_retry_chain(self):
        self.item.update(title_zh='公司动态', editorial={'version': VERSION, 'fingerprint': digest(self.item)})
        self.assertEqual(pending_tasks(self.snapshot, self.config, 1000), [])
        self.assertIsNone(next_retry(self.snapshot, self.config, 1000))

    def test_briefing_and_classification_retry_without_translation_backlog(self):
        self.item['title_zh'] = '公司动态'
        self.snapshot['briefing']['generated_at'] = None
        self.assertEqual(pending_tasks(self.snapshot, self.config, 1000), ['news_curation', 'news_summary'])
        self.assertEqual(next_retry(self.snapshot, self.config, 1000), 1120)

    def test_missing_credentials_does_not_create_endless_retry_chain(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(next_retry(self.snapshot, self.config, 1000))

    def test_retry_state_survives_without_deployment_but_cannot_roll_back_newer_state(self):
        record = {'saved_at': 950, 'router_state': {'cooldowns': {'amd/model': 1900}},
                  'translation_attempts': {'1': {'fingerprint': digest(self.item), 'last_attempt_at': 940}}}
        restored = restore_state(copy.deepcopy(self.snapshot), record)
        self.assertEqual(restored['briefing']['router_state']['cooldowns']['amd/model'], 1900)
        self.assertEqual(restored['items'][0]['translation']['last_attempt_at'], 940)
        self.snapshot['updated_at'] = 960
        self.assertEqual(restore_state(self.snapshot, record)['briefing']['router_state'], {})

    def test_only_content_progress_triggers_ai_publication(self):
        changed = copy.deepcopy(self.snapshot)
        changed.update(updated_at=1000, curation={'translation': {'pending': 1}})
        changed['briefing']['router_state'] = {'cooldowns': {'amd/model': 1900}}
        changed['briefing']['status'] = 'unavailable'
        changed['items'][0]['translation'] = {'status': 'pending', 'last_attempt_at': 1000}
        self.assertEqual(reader_content(changed), reader_content(self.snapshot))
        changed['items'][0].update(title_zh='公司动态', summary_zh='新试验结果。')
        self.assertNotEqual(reader_content(changed), reader_content(self.snapshot))


class CachedCollectionTests(unittest.TestCase):
    @patch('collect.fetch_source', side_effect=AssertionError('Retry must not fetch RSS'))
    def test_ai_only_preserves_collection_time_sources_and_existing_news(self, fetch):
        now = 1789730000
        article = {'id': 1, 'title': 'Company update', 'excerpt': 'Trial update.',
                   'url': 'https://example.org/story', 'language': 'en', 'source_id': SOURCES[0]['id'],
                   'first_seen_at': now - 100, 'last_seen_at': now - 100, 'published_at': None}
        previous = {'updated_at': now - 100, 'last_success_at': now - 100, 'items': [article],
                    'sources': [{'id': s['id'], 'status': 'ok', 'checked_at': now - 100} for s in SOURCES]}
        def enrich(items, sources, briefing, *args, **kwargs):
            items[0].update(title_zh='公司动态', summary_zh='试验进展。', event_id='1')
            return briefing, {'execution': {}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'previous.json').write_text(json.dumps(previous))
            with patch('collect.time.time', return_value=now), patch('collect.enrich', side_effect=enrich), \
                 patch('collect.summarize', return_value={'status': 'ok'}), \
                 patch('collect.CATALOG', {'companies': []}), patch('builtins.print'):
                result = collect(root / 'out', root / 'previous.json', True, ai_only=True)
        fetch.assert_not_called()
        self.assertEqual(result['last_success_at'], now - 100)
        self.assertEqual(result['sources'], previous['sources'])
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['items'][0]['title_zh'], '公司动态')
        self.assertEqual(result['items'][0]['first_seen_at'], now - 100)

    def test_ai_retry_cannot_bootstrap_an_empty_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                collect(Path(directory) / 'out', ai_only=True)
