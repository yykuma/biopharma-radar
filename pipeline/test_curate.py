import json
import os
import unittest
from unittest.mock import patch

from ai_router import Completion
from curate import canonical_url, curate, digest, group_events, parse_labels, restore
from collect import normalize, prepare_previous, SOURCES


class CurationTests(unittest.TestCase):
    def article(self, id, **extra):
        return {'id': id, 'title': f'Company trial update {id}', 'excerpt': 'Phase three trial data.',
                'first_seen_at': 1000000, 'published_at': None, 'company_ids': ['us-lly'], **extra}

    def test_tracking_removed_but_meaningful_query_preserved(self):
        self.assertEqual(canonical_url('https://EXAMPLE.org/release?id=2&utm_source=rss&fbclid=abc#top'),
                         'https://example.org/release?id=2')
        self.assertNotEqual(canonical_url('https://example.org/?id=2'), canonical_url('https://example.org/?id=3'))
        source = SOURCES[0]
        old = normalize({'title': 'Trial results', 'url': 'https://example.org/?id=2'}, source, 1000000)
        previous = {**old, 'url': old['url'] + '&utm_source=rss', 'id': 123, 'first_seen_at': 900000}
        merged, _ = prepare_previous({'items': [previous], 'sources': SOURCES}, 1000000)
        self.assertEqual(list(merged), [old['id']])
        self.assertEqual(merged[old['id']]['first_seen_at'], 900000)

    def test_groups_keep_reports_and_separate_updates(self):
        a, b, update = [self.article(i) for i in [1, 2, 3]]
        b['editorial'] = {'confidence': 'high', 'category': 'clinical', 'same_event_as': '1'}
        group_events([a, b, update])
        self.assertEqual(a['event_id'], b['event_id'])
        self.assertNotEqual(a['event_id'], update['event_id'])
        self.assertEqual(a['related_article_ids'], [2])
        self.assertEqual(b['related_article_ids'], [1])

    def test_low_confidence_different_companies_and_later_data_do_not_merge(self):
        a = self.article(1)
        for change in [{'company_ids': ['us-amgn']}, {'first_seen_at': 1800000}, {}]:
            b = self.article(2, **change)
            b['editorial'] = {'confidence': 'high' if change else 'uncertain', 'same_event_as': '1'}
            group_events([a, b])
            self.assertNotEqual(a['event_id'], b['event_id'])

    def test_stale_classification_and_unknown_references_are_rejected(self):
        a = self.article(1)
        old = {**a, 'editorial': {'fingerprint': digest(a), 'version': 1, 'category': 'clinical'}}
        restore(a, old)
        self.assertEqual(a['editorial']['category'], 'clinical')
        changed = self.article(1, excerpt='Corrected result')
        restore(changed, old)
        self.assertNotIn('editorial', changed)
        with self.assertRaises(ValueError):
            parse_labels(json.dumps([{'id': '1', 'category': 'clinical', 'confidence': 'high', 'same_event_as': '99'}]), {'1'}, {'1'})

    @patch.dict(os.environ, {'TEST_KEY': 'fixture'})
    def test_uncertain_marketing_stays_visible_and_budget_is_shared(self):
        config = {'strategy': 'round_robin', 'max_attempts_per_run': 1, 'providers': [{'id': 'test', 'enabled': True,
            'key_env': 'TEST_KEY', 'max_requests_per_day': 1, 'models': [{'id': 'model', 'enabled': True,
                'free_tier': 'free', 'tasks': ['news_translation']}]}]}
        a = self.article(1)
        def call(*args):
            return Completion(json.dumps([{'id': '1', 'category': 'marketing', 'confidence': 'uncertain', 'same_event_as': None}]), 100, 'stop')
        previous, report = curate([a], None, True, 1000000, call, config)
        self.assertEqual(a['editorial']['category'], 'unknown')
        self.assertEqual(report['marketing'], 0)
        self.assertEqual(previous['router_state']['token_usage']['test'], 100)
        b = self.article(2)
        _, report = curate([a, b], previous, True, 1000000, lambda *args: self.fail('Budget exhausted'), config)
        self.assertEqual(report['pending'], 1)
        self.assertNotIn('editorial', b)

    def test_exact_syndication_groups_without_ai_and_cycles_are_safe(self):
        a = self.article(1, title='Identical trial announcement', excerpt='A sufficiently long original announcement. ' * 5)
        b = self.article(2, title=a['title'], excerpt=a['excerpt'])
        a['editorial'] = {'confidence': 'high', 'same_event_as': '2'}
        b['editorial'] = {'confidence': 'high', 'same_event_as': '1'}
        group_events([a, b])
        self.assertEqual(a['event_id'], b['event_id'])
