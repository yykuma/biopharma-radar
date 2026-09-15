import json
import os
import unittest
from unittest.mock import patch

from ai_router import parse_briefing, summarize


class BriefingTests(unittest.TestCase):
    def test_rejects_invented_sources_and_unstructured_lists(self):
        for text in ('[1] Some news', '[{"text":"Some news","sources":[4]}]',
                     '[{"text":"Some news","sources":[]}]'):
            with self.assertRaises(ValueError):
                parse_briefing(text,3)

    @patch.dict(os.environ,{'TEST_KEY':'fixture'})
    def test_reference_numbers_follow_inputs_when_summary_reorders_articles(self):
        items=[{'id':i,'title':'News '+str(i),'excerpt':'Source excerpt','source':'Publisher',
                'url':'https://example.com/'+str(i)} for i in (1,2,3)]
        config={'strategy':'round_robin','task':'news_summary','max_attempts_per_run':1,
                'max_input_articles':20,'max_output_tokens':700,'summary_interval_hours':6,
                'providers':[{'id':'test','enabled':True,'key_env':'TEST_KEY',
                  'models':[{'id':'model','enabled':True,'free_tier':'free','tasks':['news_summary']}]}]}
        response=json.dumps([{'text':'Third article first','sources':[3]},
                             {'text':'First article second','sources':[1]}])
        result=summarize(items,enabled=True,config=config,now=100000,call=lambda *_:response)
        self.assertEqual(result['text'],'Third article first [3]\n\nFirst article second [1]')
        self.assertEqual([(r['number'],r['url']) for r in result['references']],
                         [(1,'https://example.com/1'),(3,'https://example.com/3')])
