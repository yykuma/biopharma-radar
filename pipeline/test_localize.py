import json
import os
import unittest
from unittest.mock import patch
from ai_router import Completion, summarize
from localize import apply_cached, fingerprint, localize, parse_translations
from company_registry import CATALOG, match_companies
from article_text import extract, fetch_text


class LocalizationTests(unittest.TestCase):
    def setUp(self):
        self.item={'id':1,'title':'Company reports trial results','excerpt':'Trial did not meet its primary endpoint.',
            'source_id':'source','source':'Company','url':'https://example.org/news','language':'en'}
        self.config={'strategy':'round_robin','task':'news_summary','max_attempts_per_run':1,'summary_interval_hours':6,'max_input_articles':20,'max_output_tokens':700,
            'providers':[{'id':'test','enabled':True,'max_requests_per_day':1,'key_env':'TEST_KEY',
                'models':[{'id':'model','enabled':True,'free_tier':'free','tasks':['news_translation','news_summary']}]}]}
        self.sources=[{'id':'source'}]

    @patch.dict(os.environ,{'TEST_KEY':'fixture'})
    def test_translation_and_briefing_share_daily_budget(self):
        def call(*args):return Completion(json.dumps([{'id':'1','title_zh':'公司公布试验结果','summary_zh':'试验未达到主要终点。'}]),123,'stop')
        previous=localize([self.item],self.sources,None,True,100000,call,self.config)
        self.assertEqual(self.item['title_zh'],'公司公布试验结果')
        self.assertEqual(previous['router_state']['token_usage']['test'],123)
        result=summarize([self.item],previous,True,lambda *args:self.fail('Translation exhausted daily allowance'),self.config,100000)
        self.assertEqual(result['status'],'unavailable')
        self.assertEqual(result['router_state']['daily_usage']['requests']['provider:test'],1)

    @patch.dict(os.environ,{'TEST_KEY':'fixture'})
    def test_invalid_or_truncated_translation_is_not_published(self):
        for completion in [Completion('[{"id":"2","title_zh":"错误匹配","summary_zh":"这是错误文章"}]',90,'stop'),Completion('输出被截断',40,'length')]:
            item=dict(self.item)
            result=localize([item],self.sources,None,True,100000,lambda *a:completion,self.config)
            self.assertNotIn('title_zh',item)
            self.assertEqual(item['translation']['status'],'pending')
            self.assertEqual(result['router_state']['token_usage']['test'],completion.tokens)

    def test_cached_translation_requires_matching_source_text(self):
        cached={**self.item,'title_zh':'标题','summary_zh':'摘要','content_fingerprint':fingerprint(self.item)}
        target=dict(self.item);apply_cached(target,cached,{})
        self.assertEqual(target['title_zh'],'标题')
        changed={**self.item,'excerpt':'Corrected result'};apply_cached(changed,cached,{})
        self.assertNotIn('title_zh',changed)

    def test_duplicate_translation_ids_are_rejected(self):
        with self.assertRaises(ValueError):parse_translations(json.dumps([{'id':'1'},{'id':'1'}]),{'1'})

    def test_company_identity_and_boundaries(self):
        both=match_companies('BeOne Medicines announces results',{})
        self.assertEqual({l['market'] for l in both[0]['listings']},{'US','HK'})
        self.assertEqual(match_companies('Merck KGaA develops a new drug',{}),[])
        self.assertEqual(match_companies('Accompanying Pfizermab treatment',{}),[])
        self.assertEqual(match_companies('A quarterly update',{'company_ids':['us-lly']})[0]['id'],'us-lly')
        self.assertEqual(match_companies('09926.HK announced results',{})[0]['id'],'hk-09926')
        self.assertEqual(match_companies('00013.HK announced results',{})[0]['id'],'us-hcm')
        self.assertEqual(match_companies('00512.HK announced results',{})[0]['id'],'hk-00512')
        self.assertEqual(len({c['id'] for c in CATALOG['companies']}),len(CATALOG['companies']))

    def test_article_parser_ignores_navigation_and_private_hosts(self):
        text,date=extract('<nav><p>Navigation</p></nav><article><p>A sufficiently detailed public introduction about trial results.</p></article><script type="application/ld+json">{"@type":"NewsArticle","datePublished":"2026-09-15T10:00:00Z"}</script>','article')
        self.assertNotIn('Navigation',text);self.assertEqual(date,'2026-09-15T10:00:00Z')
        self.assertEqual(fetch_text({'url':'http://127.0.0.1/private'},{'article_hosts':['example.org']}),('',None))

    def test_disabled_bootstrap_has_complete_briefing_shape(self):
        previous=localize([self.item],self.sources,None,False,100000,config=self.config)
        self.assertEqual(summarize([self.item],previous,False,config=self.config)['status'],'disabled')

    @patch.dict(os.environ,{'TEST_KEY':'fixture'})
    def test_configured_batches_process_older_backlog_first(self):
        config={**self.config,'translation':{'batch_size':2,'max_batches_per_run':2,'max_output_tokens':3000}}
        config['providers'][0]['max_requests_per_day']=10
        items=[{**self.item,'id':i,'first_seen_at':i*100} for i in [5,3,1,4,2]]
        calls=[]
        def call(_provider,_model,messages,_limit):
            inputs=json.loads(messages[-1]['content']);calls.append([a['id'] for a in inputs])
            return Completion(json.dumps([{'id':a['id'],'title_zh':'试验结果','summary_zh':'试验未达到主要终点。'} for a in inputs]),100,'stop')
        result=localize(items,self.sources,None,True,100000,call,config)
        self.assertEqual(calls,[['1','2'],['3','4']])
        self.assertEqual(result['translation_run']['translated_this_run'],4)
        self.assertEqual(result['translation_run']['pending'],1)

    @patch.dict(os.environ,{'TEST_KEY':'fixture'})
    def test_failed_batch_does_not_starve_other_pending_articles(self):
        config={**self.config,'translation':{'batch_size':1,'max_batches_per_run':1}}
        config['providers'][0]['max_requests_per_day']=10
        failed={**self.item,'first_seen_at':1}
        previous=localize([failed],self.sources,None,True,100000,
                          lambda *args:Completion('Malformed response that is not JSON.',20,'stop'),config)
        fetched=dict(self.item);apply_cached(fetched,failed,{})
        self.assertEqual(fetched['translation']['last_attempt_at'],100000)
        waiting={**self.item,'id':2,'first_seen_at':2}
        def call(_provider,_model,messages,_limit):
            self.assertEqual(json.loads(messages[-1]['content'])[0]['id'],'2')
            return Completion(json.dumps([{'id':'2','title_zh':'试验结果','summary_zh':'试验未达到主要终点。'}]),20,'stop')
        localize([fetched,waiting],self.sources,previous,True,101000,call,config)
        self.assertIn('title_zh',waiting)
        self.assertNotIn('title_zh',fetched)
