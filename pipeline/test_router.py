import os
import json
import unittest
from unittest.mock import patch
from ai_router import summarize, Completion


def briefing(text):
    return json.dumps([{'text':text,'sources':[1]}])


class Failure(Exception):
    status_code=429


class RouterTests(unittest.TestCase):
    def setUp(self):
        self.items=[{'id':1,'title':'Company reports trial update','excerpt':'A public company update','source':'Company','url':'https://example.org/news'}]
        self.config={'strategy':'round_robin','task':'news_summary','max_attempts_per_run':3,'summary_interval_hours':6,'max_input_articles':20,'max_output_tokens':100,
            'providers':[{'id':p,'enabled':True,'key_env':p.upper()+'_KEY','models':[{'id':m,'enabled':True,'free_tier':'free','tasks':['news_summary']} for m in models]} for p,models in [('a',['one','two']),('b',['three'])]]}

    @patch.dict(os.environ, {'A_KEY':'test','B_KEY':'test'})
    def test_provider_limit_skips_other_models_and_persists_cooldown(self):
        calls=[]
        def call(p,m,*args):
            calls.append(m['id'])
            if p['id']=='a':raise Failure()
            return briefing('A sufficiently long news summary from the fallback model.')
        result=summarize(self.items,enabled=True,call=call,config=self.config,now=100000)
        self.assertEqual(calls,['one','three'])
        self.assertEqual(result['router_state']['cooldowns']['provider:a'],103600)
        self.assertEqual(result['status'],'ok')

    @patch.dict(os.environ, {'A_KEY':'test','B_KEY':'test'})
    def test_rotation_and_no_duplicate_summary(self):
        previous={'router_state':{'last_model':'a/one'}}
        calls=[]
        def call(p,m,*args):calls.append(m['id']);return briefing('A sufficiently long summary with a reference [1].')
        result=summarize(self.items,previous,True,call,self.config,100000)
        self.assertEqual(calls,['two'])
        again=summarize(self.items,result,True,call,self.config,200000)
        self.assertEqual({k:v for k,v in again.items() if k != 'router_state'},
                         {k:v for k,v in result.items() if k != 'router_state'})
        self.assertEqual(len(calls),1)

    @patch.dict(os.environ, {'A_KEY':'test','B_KEY':'test'})
    def test_excludes_paid_models_and_preserves_last_good_text(self):
        for p in self.config['providers']:
            for m in p['models']:m['free_tier']='paid'
        previous={'text':'Last good summary','generated_at':1}
        result=summarize(self.items,previous,True,lambda *args:self.fail('Paid call'),self.config,100000)
        self.assertEqual(result['text'],'Last good summary')
        self.assertEqual(result['status'],'unavailable')

    @patch.dict(os.environ, {'A_KEY':'test','B_KEY':'test'})
    def test_expiry_and_daily_caps_are_enforced_and_reset(self):
        self.config['providers'][0]['expires_at']='1970-01-01T00:00:01Z'
        self.config['providers'][1]['max_requests_per_day']=1
        previous={'router_state':{'daily_usage':{'date':'1970-01-02','requests':{'provider:b':1}}}}
        result=summarize(self.items,previous,True,lambda *a:self.fail('Capped or expired call'),self.config,100000)
        self.assertEqual(result['status'],'unavailable')
        result=summarize(self.items,result,True,lambda *a:briefing('A sufficiently long next-day summary.'),self.config,200000)
        self.assertEqual(result['provider'],'b')

    @patch.dict(os.environ, {'A_KEY':'test','B_KEY':'test'})
    def test_cap_also_applies_between_models_in_same_run(self):
        self.config['providers'][0]['max_requests_per_day']=1
        calls=[]
        def call(p,m,*args):
            calls.append(m['id'])
            if p['id']=='a':raise ValueError('Failed model')
            return briefing('A sufficiently long fallback summary.')
        summarize(self.items,enabled=True,call=call,config=self.config,now=100000)
        self.assertEqual(calls,['one','three'])

    @patch.dict(os.environ, {'A_KEY':'test','B_KEY':'test'})
    def test_truncated_output_is_counted_but_not_published(self):
        self.config['max_attempts_per_run']=1
        previous={'text':'Previous complete summary'}
        result=summarize(self.items,previous,True,lambda *a:Completion('A very long but truncated output...',321,'length'),self.config,100000)
        self.assertEqual(result['text'],previous['text'])
        self.assertEqual(result['router_state']['token_usage']['a'],321)

    @patch.dict(os.environ, {'A_KEY':'test','B_KEY':'test'})
    def test_fallback_pool_stays_after_rotation(self):
        self.config['providers'][1]['routing_role']='fallback'
        result=summarize(self.items,{'router_state':{'last_model':'a/two'}},True,lambda *a:briefing('A sufficiently long primary summary.'),self.config,100000)
        self.assertEqual(result['provider'],'a')

if __name__=='__main__':unittest.main()

class RoutingChangesTests(unittest.TestCase):
    @patch.dict(os.environ, {'SENSENOVA_API_KEY': 'fixture'}, clear=True)
    def test_sensenova_requests_are_spaced_across_tasks(self):
        from ai_router import load_registry, new_state, route_text, RoutingSession
        config = load_registry()
        session = RoutingSession(new_state({}, 100000), config['execution'])
        clock = [100.0]
        starts = []
        def call(*_):
            starts.append(clock[0])
            return 'A complete response from the shared SenseNova supplier.'
        def advance(timeout):
            clock[0] += timeout
        with patch('ai_router.time.monotonic', side_effect=lambda: clock[0]), \
             patch.object(session.condition, 'wait', side_effect=advance):
            for task in ('news_translation', 'news_curation'):
                result = route_text([], session.state, {**config, 'task': task}, 100000, call, session=session)
                self.assertEqual(result['status'], 'ok')
        self.assertEqual(starts, [100.0, 130.0])
        self.assertEqual(session.max_parallel, 1)

    @patch.dict(os.environ, {key: 'fixture' for key in
                            ('AMD_API_KEY', 'SENSENOVA_API_KEY', 'MISTRAL_API_KEY', 'AGNES_API_KEY')}, clear=True)
    def test_production_has_no_attempt_cap_and_exhausts_models_without_looping(self):
        from ai_router import load_registry, new_state, route_text, candidates, ProviderError
        config = load_registry()
        self.assertIsNone(config.get('max_attempts_per_run'))
        config['task'] = 'news_translation'
        state = new_state({}, 100000)
        expected = {key for _, _, key in candidates(config, state, 100000)}
        calls = []
        def call(provider, model, *_):
            calls.append(provider['id'] + '/' + model['id'])
            if provider['id'] == 'amd':
                raise ProviderError(429, 120)
            raise TimeoutError()
        result = route_text([], state, config, 100000, call)
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(set(calls), expected)
        self.assertEqual(len(calls), len(expected))
        self.assertEqual(sum(key.startswith('amd/') for key in calls), 4)
        self.assertGreater(len(calls), 5)

    @patch.dict(os.environ, {key: 'fixture' for key in
                            ('AMD_API_KEY', 'SENSENOVA_API_KEY', 'MISTRAL_API_KEY', 'AGNES_API_KEY')}, clear=True)
    def test_primary_failures_reach_both_fallback_suppliers(self):
        from ai_router import load_registry, new_state, route_text, ProviderError
        config = load_registry()
        config['task'] = 'news_translation'
        calls = []
        def call(provider, model, *_):
            calls.append(provider['id'])
            if provider['id'] == 'amd':
                raise TimeoutError()
            if provider['id'] in ('sensenova-general', 'mistral'):
                raise ProviderError(429, 60)
            return 'A complete translation from the remaining fallback supplier.'
        result = route_text([], new_state({}, 100000), config, 100000, call)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(calls, ['amd', 'sensenova-general', 'mistral', 'agnes'])

    @patch.dict(os.environ, {'TEST_KEY': 'fixture'}, clear=True)
    def test_model_rotation_resumes_after_all_suppliers_have_a_turn(self):
        from ai_router import route_text, new_state
        config = {'strategy': 'round_robin', 'task': 'news_translation', 'max_attempts_per_run': 5,
                  'providers': [{'id': p, 'enabled': True, 'key_env': 'TEST_KEY',
                                 'routing_role': 'fallback' if p == 'backup' else 'primary',
                                 'models': [{'id': m, 'enabled': True, 'free_tier': 'free',
                                             'tasks': ['news_translation']} for m in models]}
                                for p, models in [('amd', ['one', 'two']), ('backup', ['three'])]]}
        calls = []
        def call(provider, model, *_):
            calls.append(model['id'])
            if model['id'] != 'two':
                raise TimeoutError()
            return 'A complete translation from the next AMD model.'
        result = route_text([], new_state({}, 100000), config, 100000, call)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(calls, ['one', 'three', 'two'])

    @patch.dict(os.environ, {'SENSENOVA_API_KEY':'fixture','AGNES_API_KEY':'fixture'}, clear=True)
    def test_sensenova_uses_deepseek_before_agnes_fallback(self):
        from ai_router import candidates, load_registry, new_state, route_text, ProviderError
        config = load_registry()
        config['task'] = 'news_translation'
        state = new_state({},100000)
        choices = candidates(config,state,100000)
        self.assertEqual([(p['id'],m['id']) for p,m,_ in choices],
                         [('sensenova-general','deepseek-v4-flash'),('agnes','agnes-2.5-flash')])
        calls=[]
        def call(p,m,*_):
            calls.append(p['id'])
            if p['id']=='sensenova-general':
                raise ProviderError(429,60)
            return 'A complete response from the fallback provider.'
        result=route_text([],state,config,100000,call)
        self.assertEqual(result['status'],'ok')
        self.assertEqual(calls,['sensenova-general','agnes'])

    @patch.dict(os.environ, {'TEST_KEY':'fixture'})
    def test_model_scoped_429_rotates_without_blocking_supplier(self):
        from ai_router import route_text, new_state, ProviderError
        config={'strategy':'round_robin','task':'news_translation','max_attempts_per_run':3,
                'providers':[{'id':'amd','enabled':True,'key_env':'TEST_KEY','rate_limit_scope':'model',
                'models':[{'id':m,'enabled':True,'free_tier':'free','tasks':['news_translation']} for m in ['one','two']]}]}
        calls=[]
        def call(p,m,*args):
            calls.append(m['id'])
            if m['id']=='one':raise ProviderError(429,120)
            return 'A complete response from the second model.'
        state=new_state({},100000)
        state['daily_usage']['requests']['provider:amd']=10000
        result=route_text([],state,config,100000,call)
        self.assertEqual(result['status'],'ok')
        self.assertEqual(calls,['one','two'])
        self.assertEqual(state['cooldowns'],{'amd/one':100120})
        self.assertEqual(state['daily_usage']['requests']['provider:amd'],10002)

    def test_production_registry_caps_only_openrouter(self):
        from ai_router import load_registry
        for p in load_registry()['providers']:
            if p['id']=='openrouter':
                self.assertEqual(p['max_requests_per_day'],50)
                self.assertEqual(p['quota_store'],'github')
            else:
                for entry in [p,*p['models']]:self.assertNotIn('max_requests_per_day',entry)

    @patch.dict(os.environ, {'OPENROUTER_API_KEY':'fixture'}, clear=True)
    def test_openrouter_handles_editorial_tasks_without_translation_calls(self):
        from ai_router import candidates, load_registry, new_state, route_text
        config = load_registry()
        config['providers'] = [p for p in config['providers'] if p['id']=='openrouter']
        state = new_state({},100000)
        for task in ('news_curation','news_summary'):
            self.assertTrue(candidates({**config,'task':task},state,100000))
        result = route_text([],state,{**config,'task':'news_translation'},100000,
                            lambda *_:self.fail('Editorial-only model received a translation'))
        self.assertEqual(result['status'],'unavailable')

    def test_retry_after_header(self):
        from ai_router import retry_delay
        self.assertEqual(retry_delay('120'),120)
        self.assertIsNone(retry_delay('invalid'))
        self.assertIsNone(retry_delay(None))

    @patch.dict(os.environ,{'TEST_KEY':'fixture'})
    def test_supplier_fairness_reaches_other_services_before_retrying_models(self):
        from ai_router import route_text,new_state,ProviderError
        config={'strategy':'round_robin','task':'news_translation','max_attempts_per_run':3,
                'providers':[{'id':p,'enabled':True,'key_env':'TEST_KEY','rate_limit_scope':'model',
                'models':[{'id':m,'enabled':True,'free_tier':'free','tasks':['news_translation']} for m in models]}
                for p,models in [('amd',['one','two','three','four']),('agnes',['agnes-2.5-flash'])]]}
        calls=[]
        def call(p,m,*args):
            calls.append(p['id']+'/'+m['id'])
            if p['id']=='amd':raise ProviderError(429)
            return 'A complete response from the second supplier.'
        result=route_text([],new_state({},100000),config,100000,call)
        self.assertEqual(result['status'],'ok')
        self.assertEqual(calls,['amd/one','agnes/agnes-2.5-flash'])
