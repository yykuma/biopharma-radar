import os
import unittest
from unittest.mock import patch
from ai_router import summarize, Completion


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
            return 'A sufficiently long news summary from the fallback model.'
        result=summarize(self.items,enabled=True,call=call,config=self.config,now=100000)
        self.assertEqual(calls,['one','three'])
        self.assertEqual(result['router_state']['cooldowns']['provider:a'],103600)
        self.assertEqual(result['status'],'ok')

    @patch.dict(os.environ, {'A_KEY':'test','B_KEY':'test'})
    def test_rotation_and_no_duplicate_summary(self):
        previous={'router_state':{'last_model':'a/one'}}
        calls=[]
        def call(p,m,*args):calls.append(m['id']);return 'A sufficiently long summary with a reference [1].'
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
        result=summarize(self.items,result,True,lambda *a:'A sufficiently long next-day summary.',self.config,200000)
        self.assertEqual(result['provider'],'b')

    @patch.dict(os.environ, {'A_KEY':'test','B_KEY':'test'})
    def test_cap_also_applies_between_models_in_same_run(self):
        self.config['providers'][0]['max_requests_per_day']=1
        calls=[]
        def call(p,m,*args):
            calls.append(m['id'])
            if p['id']=='a':raise ValueError('Failed model')
            return 'A sufficiently long fallback summary.'
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
        result=summarize(self.items,{'router_state':{'last_model':'a/two'}},True,lambda *a:'A sufficiently long primary summary.',self.config,100000)
        self.assertEqual(result['provider'],'a')

if __name__=='__main__':unittest.main()

class RoutingChangesTests(unittest.TestCase):
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

    def test_production_registry_has_no_daily_caps(self):
        from ai_router import load_registry
        for p in load_registry()['providers']:
            for entry in [p,*p['models']]:self.assertNotIn('max_requests_per_day',entry)

    def test_retry_after_header(self):
        from ai_router import retry_delay
        self.assertEqual(retry_delay('120'),120)
        self.assertIsNone(retry_delay('invalid'))
        self.assertIsNone(retry_delay(None))
