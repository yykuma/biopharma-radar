import base64
import json
import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from urllib.error import HTTPError

from ai_router import RoutingSession,new_state,route_text
from quota_ledger import reserve_daily,LedgerUnavailable


class FakeLedger:
    def __init__(self):
        self.record=None
        self.revision=0
        self.lock=threading.Lock()

    def __call__(self,method,path,payload=None):
        with self.lock:
            if method=='GET':
                if self.record is None:raise HTTPError(path,404,'missing',{},None)
                return {'sha':str(self.revision),'content':base64.b64encode(json.dumps(self.record).encode()).decode()}
            if payload.get('sha') != (str(self.revision) if self.record is not None else None):
                raise HTTPError(path,409,'conflict',{},None)
            self.record=json.loads(base64.b64decode(payload['content']))
            self.revision+=1
            return {}


class LedgerTests(unittest.TestCase):
    def test_daily_limit_survives_restarts_and_resets_after_utc_boundary(self):
        api=FakeLedger()
        for n in range(1,51):
            self.assertEqual(reserve_daily('openrouter',50,100000,api)['used'],n)
        self.assertFalse(reserve_daily('openrouter',50,110000,api)['reserved'])
        self.assertEqual(api.revision,50)
        fresh=reserve_daily('openrouter',50,172800,api)
        self.assertEqual(fresh['used'],1)
        self.assertEqual(fresh['reset_at'],259200)

    def test_concurrent_sessions_cannot_exceed_fifty(self):
        api=FakeLedger()
        def reserve(_):
            try:return reserve_daily('openrouter',50,100000,api)['reserved']
            except LedgerUnavailable:return False
        with ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(reserve,range(100)))
        self.assertEqual(sum(results),50)
        self.assertEqual(api.record['used'],50)

    @patch.dict(os.environ,{'TEST_KEY':'fixture'})
    def test_failed_inference_is_counted_and_new_session_keeps_count(self):
        api=FakeLedger()
        config={'strategy':'round_robin','task':'news_translation','max_attempts_per_run':1,
                'providers':[{'id':'openrouter','enabled':True,'key_env':'TEST_KEY','quota_store':'github',
                'max_requests_per_day':50,'models':[{'id':'example:free','enabled':True,'free_tier':'free','tasks':['news_translation']}]}]}
        with patch('ai_router.reserve_daily',side_effect=lambda p,l,n:reserve_daily(p,l,n,api)):
            for expected in [1,2]:
                session=RoutingSession(new_state({},100000))
                result=route_text([],session.state,config,100000,lambda *_:'bad',session=session)
                self.assertEqual(result['status'],'unavailable')
                self.assertEqual(api.record['used'],expected)
                self.assertEqual(session.state['daily_usage']['requests']['provider:openrouter'],expected)

    @patch.dict(os.environ,{'TEST_KEY':'fixture'})
    def test_ledger_failure_does_not_call_model(self):
        config={'strategy':'round_robin','task':'news_translation','max_attempts_per_run':1,
                'providers':[{'id':'openrouter','enabled':True,'key_env':'TEST_KEY','quota_store':'github',
                'max_requests_per_day':50,'models':[{'id':'example:free','enabled':True,'free_tier':'free','tasks':['news_translation']}]}]}
        with patch('ai_router.reserve_daily',side_effect=LedgerUnavailable()):
            result=route_text([],new_state({},100000),config,100000,lambda *_:self.fail('Uncounted request'))
        self.assertEqual(result['status'],'unavailable')
