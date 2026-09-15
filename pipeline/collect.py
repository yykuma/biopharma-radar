"""Run pinned TrendRadar modules and export a public, bounded news snapshot."""
import argparse
import concurrent.futures
import hashlib
import html
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from xml.etree.ElementTree import Element, SubElement, ElementTree

from trendradar.crawler.rss import RSSFetcher, RSSFeedConfig
from trendradar.crawler.fetcher import DataFetcher
from ai_router import summarize

ROOT = Path(__file__).resolve().parents[1]
SOURCES = json.loads((ROOT / 'config/sources.json').read_text())
KEYWORDS = re.compile(r'医药|医疗|生物|药业|药物|制药|创新药|临床|获批|FDA|biotech|pharma|healthcare|drug|therapy|therapeutic|cancer|oncology|恒瑞|百济|百利|信达|康方|石药|中国生物制药|药明|翰森|复星|迈瑞|礼来|阿斯利康|辉瑞|诺华|罗氏|司美格鲁肽', re.I)
COMPANIES = {
    '恒瑞': ['A','HK'], 'Hengrui':['A','HK'], 'Mindray':['A'], 'Aier':['A'], 'Pien Tze Huang':['A'], '药明康德':['A','HK'], 'WuXi AppTec':['A','HK'], 'CSPC':['HK'], 'Sino Biopharmaceutical':['HK'], 'Akeso':['HK'], 'Innovent':['HK'], 'Hansoh':['HK'], 'GSK':['US'], 'Moderna':['US'], '迈瑞': ['A'], '爱尔眼科':['A'], '片仔癀':['A'],
    '百利天恒':['A'], '康方':['HK'], '信达生物':['HK'], '石药':['HK'],
    '中国生物制药':['HK'], '药明生物':['HK'], '翰森':['HK'],
    '礼来':['US'], 'Lilly':['US'], 'Pfizer':['US'], '辉瑞':['US'],
    'AbbVie':['US'], 'Amgen':['US'], 'Gilead':['US'], 'Regeneron':['US'],
    'Vertex':['US'], 'Merck':['US'], 'Johnson & Johnson':['US']}
GROUPS = {'A':'A 股', 'HK':'港股', 'US':'美股', 'GLOBAL':'全球医药'}


def plain(value):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html.unescape(value or ''))).strip()


def timestamp(value):
    try:
        if isinstance(value, (int, float)):
            return int(value / 1000 if value > 10**11 else value)
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return int(dt.replace(tzinfo=dt.tzinfo or timezone.utc).timestamp())
    except (ValueError, TypeError):
        return None


def normalize(row, source, now):
    url = row.get('url', '')
    parts = urlsplit(url)
    if parts.scheme not in ('http', 'https') or not parts.hostname:
        return None
    url = urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ''))
    title = plain(row.get('title', ''))[:500]
    if not title or ((source.get('platform') or source['id'].endswith('yahoo')) and not KEYWORDS.search(title+' '+plain(row.get('summary','')))):
        return None
    published = timestamp(row.get('published_at') or row.get('pubDate'))
    if published and (published < now - 30*86400 or published > now + 86400):
        return None
    names = [name for name in COMPANIES if name.casefold() in title.casefold()]
    markets = sorted({m for name in names for m in COMPANIES[name]})
    if not markets:
        markets = ['GLOBAL' if source['id'] in ('a-yahoo','hk-yahoo') else source['market']]
    return dict(id=int(hashlib.sha256(url.encode()).hexdigest()[:12], 16), title=title,
                url=url, source=source['name'], source_id=source['id'], markets=markets,
                companies=names, market_basis='company_alias' if names else 'source_scope',
                published_at=published, first_seen_at=now, last_seen_at=now,
                excerpt=plain(row.get('summary', ''))[:400],
                excerpt_kind='source_excerpt', language='zh' if re.search(r'[\u4e00-\u9fff]',title) else 'en')


def fetch_source(source):
    now = int(time.time())
    try:
        if source.get('platform'):
            text, _, _ = DataFetcher().fetch_data((source['platform'], source['name']), max_retries=0)
            if text is None:
                raise ValueError('Upstream fetch failed')
            payload = json.loads(text)
            rows = payload.get('items', [])
            error = DataFetcher._check_domain_safety(rows, source['domain'])
            if error:
                raise ValueError('Source link validation failed')
        else:
            feed = RSSFeedConfig(id=source['id'], name=source['name'], url=source['url'], max_items=100)
            items, error = RSSFetcher([feed], timeout=20).fetch_feed(feed)
            if error:
                raise ValueError(error)
            rows = [vars(item) for item in items]
        articles = [item for row in rows if (item := normalize(row, source, now))]
        state = 'ok' if rows else 'empty'
        return articles, dict(id=source['id'], name=source['name'], status=state, checked_at=now,
                             received=len(rows), matched=len(articles), error=None)
    except Exception as exc:
        return [], dict(id=source['id'], name=source['name'], status='error', checked_at=now,
                        received=0, matched=0, error=plain(str(exc))[:180])



def collect(out, previous_path=None, ai_enabled=False):
    out.mkdir(parents=True, exist_ok=True)
    previous = json.loads(previous_path.read_text()) if previous_path and previous_path.exists() else {}
    now = int(time.time())
    merged = {a['id']:a for a in previous.get('items', []) if (a.get('published_at') or a['first_seen_at']) > now-30*86400}
    states=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for articles, state in pool.map(fetch_source, SOURCES):
            states.append(state)
            for article in articles:
                prior=merged.get(article['id'])
                if prior:
                    article['first_seen_at']=prior['first_seen_at']
                merged[article['id']]=article
    items=sorted(merged.values(), key=lambda a: (a['published_at'] or a['first_seen_at'],a['id']),reverse=True)[:1500]
    success=any(s['status']=='ok' for s in states)
    snapshot=dict(schema_version='1.0', updated_at=now, last_success_at=now if success else previous.get('last_success_at'),
                  collection_status='ok' if all(s['status']=='ok' for s in states) else 'partial' if success else 'failed',
                  coverage_note='基于已配置源和公司别名匹配，非全市场覆盖；市场标签可能来自源的范围。发布时间缺失时使用首次发现时间排序。',
                  sources=states, items=items, total=len(items),
                  briefing=summarize(items,previous.get('briefing'),ai_enabled))
    (out/'latest.json').write_text(json.dumps(snapshot,ensure_ascii=False,separators=(',',':')))
    (out/'briefing.json').write_text(json.dumps(snapshot['briefing'],ensure_ascii=False,indent=2))
    for market in GROUPS:
        dest=out/'markets';dest.mkdir(exist_ok=True)
        entries=[a for a in items if market in a['markets']]
        (dest/(market.lower()+'.json')).write_text(json.dumps({'schema_version':'1.0','market':market,'updated_at':now,'items':entries},ensure_ascii=False))
    rss=Element('rss',version='2.0');channel=SubElement(rss,'channel')
    for k,v in {'title':'医药动态','link':os.environ.get('SITE_URL', 'https://biopharma-radar.pages.dev').rstrip('/')+'/','description':'A股、港股、美股医疗与生物公司新闻'}.items():SubElement(channel,k).text=v
    for a in items[:100]:
        node=SubElement(channel,'item')
        for k,v in {'title':a['title'],'link':a['url'],'guid':a['url'],'description':a['excerpt']}.items():SubElement(node,k).text=v
        from email.utils import formatdate
        SubElement(node,'pubDate').text=formatdate(a['published_at'] or a['first_seen_at'],usegmt=True)
    ElementTree(rss).write(out/'feed.xml',encoding='utf-8',xml_declaration=True)
    print(json.dumps({'news':len(items),'sources':states,'ai_status':snapshot['briefing']['status']},ensure_ascii=False))
    if not items:
        raise RuntimeError('No live or cached news; refusing to publish an empty snapshot')
    return snapshot


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=ROOT/'frontend/public/data');p.add_argument('--previous',type=Path);p.add_argument('--ai',action='store_true');args=p.parse_args()
    collect(args.output,args.previous,args.ai)
