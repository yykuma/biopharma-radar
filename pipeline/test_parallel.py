import json
import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from unittest.mock import patch

from ai_router import Completion, ProviderError, RoutingSession, candidates, new_state, route_text
from editorial import enrich


@patch.dict(os.environ, {'TEST_KEY': 'fixture'})
class ParallelTests(unittest.TestCase):
    def config(self, providers=('amd', 'sense')):
        return {'strategy': 'round_robin', 'task': 'news_translation', 'max_attempts_per_run': 3,
                'providers': [{'id': name, 'enabled': True, 'key_env': 'TEST_KEY', 'max_requests_per_day': 10,
                    'models': [{'id': 'one', 'enabled': True, 'free_tier': 'free',
                                'tasks': ['news_translation', 'news_summary']}]} for name in providers]}

    def test_different_suppliers_actually_overlap_and_preserve_usage(self):
        config = self.config()
        session = RoutingSession(new_state({}, 100000))
        barrier = threading.Barrier(2)
        called = []

        def call(provider, *_):
            with session.condition:
                called.append(provider['id'])
            barrier.wait(timeout=3)
            return Completion('A complete independently generated response.', 20, 'stop')

        def task():
            return route_text([], session.state, config, 100000, call, session=session)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(task) for _ in range(2)]
            results = [f.result(timeout=5) for f in futures]
        self.assertEqual({r['status'] for r in results}, {'ok'})
        self.assertEqual(set(called), {'amd', 'sense'})
        self.assertEqual(session.max_parallel, 2)
        self.assertEqual(sum(session.state['token_usage'].values()), 40)
        self.assertEqual(session.state['daily_usage']['requests']['provider:amd'], 1)
        self.assertEqual(session.state['daily_usage']['requests']['provider:sense'], 1)

    def test_two_sensenova_pools_share_one_slot_but_keep_separate_quotas(self):
        config = self.config(('flash', 'general'))
        for provider in config['providers']:
            provider.update(supplier='sensenova', max_requests_per_day=1)
        session = RoutingSession(new_state({}, 100000))
        first = session.reserve(config, 100000, set())
        entered = threading.Event()

        def reserve_second():
            entered.set()
            return session.reserve(config, 100000, set())

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(reserve_second)
            self.assertTrue(entered.wait(timeout=1))
            with self.assertRaises(TimeoutError):
                future.result(timeout=0.05)
            with session.condition:
                session.busy.remove(first[3])
                session.condition.notify_all()
            second = future.result(timeout=1)
        self.assertEqual(first[0]['id'], 'flash')
        self.assertEqual(second[0]['id'], 'general')
        self.assertEqual(session.max_parallel, 1)
        self.assertEqual(session.state['daily_usage']['requests']['provider:flash'], 1)
        self.assertEqual(session.state['daily_usage']['requests']['provider:general'], 1)

    def test_concurrent_reservations_never_exceed_daily_cap(self):
        config = self.config(('amd',))
        config['providers'][0]['max_requests_per_day'] = 3
        session = RoutingSession(new_state({}, 100000))

        def task(_):
            return route_text([], session.state, config, 100000,
                lambda *_: Completion('A complete bounded response from the provider.', 10, 'stop'), session=session)

        with ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(task, range(20)))
        self.assertEqual(sum(r['status'] == 'ok' for r in results), 3)
        self.assertEqual(session.state['daily_usage']['requests']['provider:amd'], 3)
        self.assertEqual(session.state['token_usage']['amd'], 30)
        self.assertEqual(session.max_parallel, 1)

    def test_supplier_rate_limit_applies_to_other_models_and_pools(self):
        config = self.config(('flash', 'general', 'amd'))
        for provider in config['providers'][:2]:
            provider['supplier'] = 'sensenova'
        session = RoutingSession(new_state({}, 100000))
        called = []

        def call(provider, *_):
            called.append(provider['id'])
            if provider['id'] == 'flash':
                raise ProviderError(429)
            return 'A complete successful response from AMD.'

        result = route_text([], session.state, config, 100000, call, session=session)
        self.assertEqual(called, ['flash', 'amd'])
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(session.state['cooldowns']['supplier:sensenova'], 103600)

    def test_model_rotation_is_remembered_per_supplier(self):
        config = self.config(('flash', 'general', 'amd'))
        for provider in config['providers'][:2]:
            provider['supplier'] = 'sensenova'
        state = new_state({'last_model': 'amd/one', 'last_models': {'sensenova': 'flash/one'}}, 100000)
        choices = candidates(config, state, 100000)
        self.assertEqual([p['id'] for p, _, _ in choices if p.get('supplier') == 'sensenova'], ['general', 'flash'])

    @patch('localize.fetch_text', return_value=('', None))
    def test_translation_and_curation_integrate_without_losing_fields_or_counters(self, _fetch):
        config = self.config()
        item = {'id': 1, 'title': 'Company reports trial results', 'excerpt': 'The primary endpoint was not met.',
                'source': 'Company', 'source_id': 'company', 'language': 'en', 'first_seen_at': 100000,
                'company_ids': [], 'url': 'https://example.org/news'}
        barrier = threading.Barrier(2)

        def call(_provider, _model, messages, _limit):
            barrier.wait(timeout=3)
            data = json.loads(messages[-1]['content'])
            if isinstance(data, list):
                rows = [{'id': '1', 'title_zh': '公司公布临床试验结果', 'summary_zh': '试验未达到主要终点。'}]
            else:
                rows = [{'id': '1', 'category': 'clinical', 'confidence': 'high', 'same_event_as': None}]
            return Completion(json.dumps(rows), 25, 'stop')

        previous, report = enrich([item], [{'id': 'company'}], None, True, 100000, call, config)
        self.assertEqual(item['title_zh'], '公司公布临床试验结果')
        self.assertEqual(item['editorial']['category'], 'clinical')
        self.assertEqual(item['related_article_ids'], [])
        self.assertEqual(sum(previous['router_state']['token_usage'].values()), 50)
        self.assertEqual(report['execution']['max_observed_parallel'], 2)
        self.assertEqual({a['task'] for a in report['execution']['attempts']}, {'translation', 'curation'})
