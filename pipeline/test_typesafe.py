import json
import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from ai_router import candidates, invoke, load_registry, new_state, route_text
from typesafe_adapter import build_request, parse_response


class TypeSafeTests(unittest.TestCase):
    def setUp(self):
        self.model = {'id': 'jev-1.13.0', 'tasks': ['news_curation']}
        self.messages = [{'role': 'user', 'content': json.dumps({'articles': [
            {'id': '123456789012345', 'title': 'Trial update', 'text': 'Clinical results.'},
            {'id': '987654321098765', 'title': 'Another report', 'text': 'Same clinical results.'}], 'references': []})}]
        self.payload, self.articles, self.aliases, self.by_id = build_request(self.model, self.messages)

    def answer(self, choice, confidence):
        return {'choice': choice, 'confidence': confidence, 'probabilities': {choice: confidence}}

    def response(self):
        return {'answers': {'a1_category': self.answer('clinical', 0.99),
                            'a1_event': self.answer('a2', 0.99),
                            'a2_category': self.answer('marketing', 0.60),
                            'a2_event': self.answer('a1', 0.70)}}

    def test_deterministic_ids_and_independent_conservative_thresholds(self):
        rows = json.loads(parse_response(self.response(), self.payload, self.articles, self.aliases, self.by_id, self.model))
        self.assertEqual(rows[0]['id'], '123456789012345')
        self.assertEqual(rows[0]['same_event_as'], '987654321098765')
        self.assertEqual(rows[1]['confidence'], 'uncertain')
        self.assertIsNone(rows[1]['same_event_as'])
        self.assertNotIn('a1', self.payload['questions']['a1_event']['criteria'])

    def test_invalid_or_missing_answers_are_rejected(self):
        for kind in ('missing', 'unknown', 'nan'):
            data = self.response()
            if kind == 'missing': del data['answers']['a2_event']
            elif kind == 'unknown': data['answers']['a1_category'] = self.answer('made_up', 1)
            else: data['answers']['a1_category']['confidence'] = float('nan')
            with self.assertRaises(ValueError):
                parse_response(data, self.payload, self.articles, self.aliases, self.by_id, self.model)

    @patch.dict(os.environ, {'TYPESAFE_API_KEY': 'fixture', 'AMD_API_KEY': 'fixture', 'SENSENOVA_API_KEY': 'fixture'}, clear=True)
    def test_typesafe_is_editorial_first_and_never_used_for_generation(self):
        config = load_registry()
        for task in ('news_translation', 'news_summary', 'news_curation'):
            choices = candidates({**config, 'task': task}, new_state({}, 100000), 100000)
            names = [p['id'] for p, _, _ in choices]
            if task == 'news_curation': self.assertEqual(names[0], 'typesafe')
            else:
                self.assertNotIn('typesafe', names)
                self.assertEqual(names[0], 'amd')

    @patch.dict(os.environ, {'TYPESAFE_API_KEY': 'fixture', 'AMD_API_KEY': 'fixture', 'SENSENOVA_API_KEY': 'fixture'}, clear=True)
    def test_jev_unavailable_falls_back_through_all_amd_models_then_sensenova(self):
        config = load_registry()
        config['task'] = 'news_curation'
        config['execution']['supplier_min_interval_seconds'] = {}
        calls = []
        def call(provider, model, *args):
            calls.append(provider['id'] + '/' + model['id'])
            if provider['id'] == 'typesafe':
                return invoke(provider, model, self.messages, 1000)
            if provider['id'] == 'amd': raise TimeoutError()
            return 'A valid sufficiently long fallback response.'
        with patch('typesafe_adapter.urlopen', side_effect=HTTPError('https://api.typesafe.ai/v1/systemone', 404, 'Unavailable', {}, None)):
            result = route_text(self.messages, new_state({}, 100000), config, 100000, call)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(calls, ['typesafe/jev-1.13.0', 'amd/DeepSeek-V4-Flash-0731',
                                'amd/Qwen3.8-Flash-Next', 'amd/GLM-5.3-Flash', 'sensenova-general/deepseek-v4-flash'])
        self.assertIn('typesafe/jev-1.13.0', result['router_state']['cooldowns'])
