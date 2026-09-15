import unittest
from collect import normalize, classify


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
        self.assertEqual(normalize(self.row,self.source,1789470783)['markets'],['A','HK'])
        self.row['title']='Technology company releases new phone'
        self.assertIsNone(normalize(self.row,self.source,1789470783))

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

    def test_content_type_follows_source_format_and_updates_cached_articles(self):
        source = {**self.source, 'publisher':'Publisher', 'content_type':'brief'}
        article = {'title':'Drug market featuring Merck KGaA', 'markets':['US']}
        classify(article, source)
        self.assertEqual(article['markets'], ['GLOBAL'])
        self.assertEqual(article['content_type'], 'brief')
        self.assertEqual(article['publisher'], 'Publisher')
        self.assertEqual(normalize(self.row, self.source, 1789470783)['content_type'], 'news')
