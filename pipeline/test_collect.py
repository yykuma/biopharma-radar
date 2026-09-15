import unittest
from collect import normalize, classify, prepare_previous, SOURCES


class NormalizeTests(unittest.TestCase):
    def setUp(self):
        self.source = {'id':'a-yahoo','name':'Yahoo','market':'A'}
        self.row = {'title':'Pharma company launches new medicine','url':'https://example.org/news#section'}

    def test_ticker_feed_does_not_prove_market(self):
        article = normalize(self.row, self.source, 1789470783)
        self.assertEqual(article['markets'], ['GLOBAL'])
        self.assertIsNone(article['published_at'])
        self.assertEqual(article['url'], 'https://example.org/news')

    def test_cross_listed_company_and_unrelated_news(self):
        self.row['title']='恒瑞医药发布公司新闻'
        self.assertEqual(normalize(self.row,self.source,1789470783)['markets'],['HK'])

    def test_rejects_unsafe_urls_and_old_items(self):
        self.row['url']='javascript:alert(1)'
        self.assertIsNone(normalize(self.row,self.source,1789470783))
        self.row['url']='https://example.org/news'
        self.row['published_at']='2020-01-01T00:00:00Z'
        self.assertIsNone(normalize(self.row,self.source,1789470783))

    def test_german_merck_is_not_us_merck(self):
        self.row['title'] = 'Drug market featuring Merck KGaA'
        self.assertEqual(normalize(self.row, self.source, 1789470783)['markets'], ['GLOBAL'])
        self.row['title'] = 'Drug market featuring Merck KGaA and Merck & Co.'
        self.assertEqual(normalize(self.row, self.source, 1789470783)['markets'], ['US'])

    def test_exchange_codes_classify_financial_wire_items(self):
        source = {'id':'gelonghui', 'name':'Gelonghui', 'market':'GLOBAL', 'content_type':'brief'}
        for title, market in [('康为世纪(688426.SH)：公司公告','GLOBAL'),
                              ('东北制药(000597.SZ)：公司公告','GLOBAL'),
                              ('康宁杰瑞制药-B(09966.HK)：公司公告','HK'),
                              ('医药行业动态','GLOBAL')]:
            with self.subTest(title=title):
                article=normalize({**self.row, 'title':title}, source, 1789470783)
                self.assertEqual(article['markets'], [market])

    def test_content_type_follows_source_format_and_updates_cached_articles(self):
        source = {**self.source, 'publisher':'Publisher', 'content_type':'brief'}
        article = {'title':'Drug market featuring Merck KGaA', 'markets':['US']}
        classify(article, source)
        self.assertEqual(article['markets'], ['GLOBAL'])
        self.assertEqual(article['content_type'], 'brief')
        self.assertEqual(article['publisher'], 'Publisher')
        self.assertEqual(normalize(self.row, self.source, 1789470783)['content_type'], 'news')


class SourceScopeTests(unittest.TestCase):
    def test_source_change_removes_retired_news_and_briefing_but_keeps_router_state(self):
        state={'last_model':'provider/model', 'token_usage':{'provider':123}}
        old={'id':1,'source_id':'a-google','title':'School event','first_seen_at':100}
        keep={'id':2,'source_id':SOURCES[0]['id'],'title':'Lilly company news','first_seen_at':100}
        previous={'sources':[{'id':'a-google'}], 'items':[old,keep],
                  'briefing':{'text':'Old source summary','generated_at':100,'router_state':state}}
        items, briefing=prepare_previous(previous, 200)
        self.assertEqual(list(items), [2])
        self.assertEqual(briefing['status'], 'pending')
        self.assertIsNone(briefing['generated_at'])
        self.assertEqual(briefing['references'], [])
        self.assertEqual(briefing['router_state'], state)

    def test_unchanged_sources_retain_cached_briefing(self):
        briefing={'status':'ok','text':'Current summary','generated_at':100}
        _, retained=prepare_previous({'sources':SOURCES,'briefing':briefing}, 200)
        self.assertEqual(retained, briefing)
