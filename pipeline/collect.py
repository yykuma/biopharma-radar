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
from urllib.parse import urlsplit
from xml.etree.ElementTree import Element, SubElement, ElementTree

from trendradar.crawler.rss import RSSFetcher, RSSFeedConfig
from ai_router import summarize, RoutingSession, load_registry, new_state
from company_registry import CATALOG, match_companies
from localize import apply_cached, SEED_PATH
from curate import canonical_url, restore
from editorial import enrich

ROOT = Path(__file__).resolve().parents[1]
SOURCES = json.loads((ROOT / 'config/sources.json').read_text())
GROUPS = {'US':'美股', 'HK':'港股', 'GLOBAL':'行业动态'}
RETENTION_DAYS = 90
MAX_ITEMS = 5000


def classify(article, source):
    companies = match_companies(article['title']+' '+article.get('excerpt',''),source)
    markets = sorted({listing['market'] for c in companies for listing in c['listings']})
    ticker_hk = bool(re.search(r'\b\d{4,5}\.HK\b',article['title'],re.I))
    if ticker_hk and 'HK' not in markets: markets.append('HK')
    article.update(companies=[c.get('name_zh') or c['name'] for c in companies],
                   company_ids=[c['id'] for c in companies],
                   markets=markets or [source['market'] if source['market'] in GROUPS and not source['id'].endswith('yahoo') else 'GLOBAL'],
                   market_basis='company_registry' if companies else 'ticker' if ticker_hk else 'source_scope',
                   source=source['name'], publisher=source.get('publisher', source['name']),
                   source_kind=source.get('source_kind','media'),
                   content_type=source.get('content_type', 'news'), content_type_basis='source_format')
    return article


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
    url = canonical_url(url)
    title = plain(row.get('title', ''))[:500]
    if not title:
        return None
    published = timestamp(row.get('published_at') or row.get('pubDate'))
    if published and (published < now - RETENTION_DAYS*86400 or published > now + 86400):
        return None
    return classify(dict(id=int(hashlib.sha256(url.encode()).hexdigest()[:12], 16), title=title,
                url=url, source_id=source['id'],
                published_at=published, first_seen_at=now, last_seen_at=now,
                excerpt=plain(row.get('summary', ''))[:400],
                excerpt_kind='source_excerpt', language='zh' if re.search(r'[\u4e00-\u9fff]',title) else 'en'), source)


def fetch_source(source, previous_state=None, cached_count=0):
    now = int(time.time())
    previous_state = previous_state or {}
    signature = hashlib.sha256(json.dumps([source['url'],source.get('max_items',100),RETENTION_DAYS]).encode()).hexdigest()
    base = dict(id=source['id'], name=source['name'], publisher=source.get('publisher', source['name']),
                checked_at=now, received=0, matched=0, new_articles=0, updated_articles=0)
    headers = {}
    if cached_count and previous_state.get('feed_signature') == signature:
        for stored, header in [('etag','If-None-Match'),('last_modified','If-Modified-Since')]:
            value = previous_state.get(stored)
            if isinstance(value,str) and len(value)<=512 and '\r' not in value and '\n' not in value:
                headers[header] = value
    try:
        feed = RSSFeedConfig(id=source['id'], name=source['name'], url=source['url'], max_items=source.get('max_items',100))
        fetcher = RSSFetcher([feed], timeout=20)
        try:
            response = fetcher.session.get(feed.url, timeout=20, headers=headers)
            response.raise_for_status()
            if response.status_code == 304:
                if not headers:
                    raise ValueError('Received 304 without a valid cached feed')
                return [], {**previous_state, **base, 'status':'ok', 'matched':cached_count,
                            'fetch_status':'not_modified', 'http_status':304, 'response_bytes':0, 'error':None}
            if len(response.content)>3_000_000:
                raise ValueError('RSS exceeds size limit')
            parsed = fetcher.parser.parse(response.text, feed.url)
            if feed.max_items > 0:
                parsed = parsed[:feed.max_items]
            rows = [vars(item) for item in parsed]
            articles = [item for row in rows if (item := normalize(row, source, now))]
            metadata = {key:value for key,header in [('etag','ETag'),('last_modified','Last-Modified')]
                        if isinstance(value:=response.headers.get(header),str) and len(value)<=512}
            return articles, {**base, **metadata, 'feed_signature':signature, 'status':'ok' if rows else 'empty',
                              'received':len(rows), 'matched':len(articles), 'fetch_status':'modified',
                              'http_status':response.status_code, 'response_bytes':len(response.content), 'error':None}
        finally:
            fetcher.session.close()
    except Exception as exc:
        return [], {**previous_state, **base, 'status':'error', 'fetch_status':'error',
                    'error':plain(str(exc))[:180]}



def prepare_previous(previous, now):
    source_by_id = {s['id']: s for s in SOURCES}
    merged = {}
    for item in previous.get('items', []):
        source = source_by_id.get(item['source_id'])
        if source and (item.get('published_at') or item['first_seen_at']) > now - RETENTION_DAYS * 86400:
            item = dict(item)
            if item.get('url'):
                item['url'] = canonical_url(item['url'])
                item['id'] = int(hashlib.sha256(item['url'].encode()).hexdigest()[:12], 16)
            prior = merged.get(item['id'])
            if prior:
                item['first_seen_at'] = min(item['first_seen_at'], prior['first_seen_at'])
            merged[item['id']] = classify(item, source)
    briefing = previous.get('briefing')
    previous_sources = {s['id'] for s in previous.get('sources', [])}
    if previous_sources != set(source_by_id):
        briefing = {'status':'pending', 'text':'新闻源已更新，等待生成简报。',
                    'generated_at':None, 'references':[],
                    'router_state':(briefing or {}).get('router_state', {})}
    return merged, briefing


def collect(out, previous_path=None, ai_enabled=False):
    out.mkdir(parents=True, exist_ok=True)
    previous = json.loads(previous_path.read_text()) if previous_path and previous_path.exists() else {}
    now = int(time.time())
    merged, previous_briefing = prepare_previous(previous, now)
    seed=json.loads(SEED_PATH.read_text()) if SEED_PATH.exists() else {}
    states=[]
    previous_states={s['id']:s for s in previous.get('sources',[])}
    jobs=[(source,previous_states.get(source['id']),sum(a['source_id']==source['id'] for a in merged.values())) for source in SOURCES]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for articles, state in pool.map(lambda job: fetch_source(*job), jobs):
            states.append(state)
            for article in articles:
                prior=merged.get(article['id'])
                if prior:
                    article['first_seen_at']=prior['first_seen_at']
                    if (article['title'],article['excerpt']) != (prior['title'],prior.get('excerpt','')):
                        state['updated_articles'] += 1
                else:
                    state['new_articles'] += 1
                restore(article,prior)
                apply_cached(article,prior,seed)
                merged[article['id']]=article
    items=sorted(merged.values(), key=lambda a: (a['published_at'] or a['first_seen_at'],a['id']),reverse=True)[:MAX_ITEMS]
    for item in items:
        apply_cached(item,item,seed)
    config = load_registry()
    session = RoutingSession(new_state((previous_briefing or {}).get('router_state',{}),now),config.get('execution'))
    previous_briefing, curation = enrich(items,SOURCES,previous_briefing,ai_enabled,now,config=config,session=session)
    visible = []
    events = set()
    for item in items:
        if item.get("editorial", {}).get("category") != "marketing" and item["event_id"] not in events:
            visible.append(item)
            events.add(item["event_id"])
    success=any(s['status']=='ok' for s in states)
    snapshot=dict(schema_version='1.0', updated_at=now, last_success_at=now if success else previous.get('last_success_at'),
                  retention={'days':RETENTION_DAYS,'max_items':MAX_ITEMS},
                  collection_status='ok' if all(s['status']=='ok' for s in states) else 'partial' if success else 'failed',
                  coverage_note='专业医药媒体与公司官方公告；公司名录与新闻覆盖分别维护，美港均为部分新闻覆盖。中文为来源翻译或摘要，原文保留。',
                  sources=states, items=items, total=len(items), curation=curation,
                  briefing=summarize(visible,previous_briefing,ai_enabled,config=config,now=now,session=session))
    curation['execution'].update(session.report())
    catalog={**CATALOG,'companies':[{**c,'news_count':sum(c['id'] in a['company_ids'] for a in items),'official_source_ids':[s['id'] for s in SOURCES if c['id'] in s.get('company_ids',[])]} for c in CATALOG['companies']]}
    (out/'companies.json').write_text(json.dumps(catalog,ensure_ascii=False,separators=(',',':')))
    by_company=out/'companies';by_company.mkdir(exist_ok=True)
    for company in catalog['companies']:
        (by_company/(company['id']+'.json')).write_text(json.dumps({'schema_version':'1.0','updated_at':now,'company':company,'items':[a for a in items if company['id'] in a['company_ids']]},ensure_ascii=False,separators=(',',':')))
    (out/'latest.json').write_text(json.dumps(snapshot,ensure_ascii=False,separators=(',',':')))
    (out/'briefing.json').write_text(json.dumps(snapshot['briefing'],ensure_ascii=False,indent=2))
    (out/'markets'/'a.json').unlink(missing_ok=True)
    for market in GROUPS:
        dest=out/'markets';dest.mkdir(exist_ok=True)
        entries=[a for a in items if market in a['markets']]
        (dest/(market.lower()+'.json')).write_text(json.dumps({'schema_version':'1.0','market':market,'updated_at':now,'items':entries},ensure_ascii=False))
    rss=Element('rss',version='2.0');channel=SubElement(rss,'channel')
    for k,v in {'title':'医药动态','link':os.environ.get('SITE_URL', 'https://biopharma-radar.pages.dev').rstrip('/')+'/','description':'美股为主、港股补充的生物医药行业新闻'}.items():SubElement(channel,k).text=v
    for a in visible[:100]:
        node=SubElement(channel,'item')
        for k,v in {'title':a.get('title_zh') or a['title'],'link':a['url'],'guid':a['url'],'description':a.get('summary_zh') or a['excerpt']}.items():SubElement(node,k).text=v
        from email.utils import formatdate
        SubElement(node,'pubDate').text=formatdate(a['published_at'] or a['first_seen_at'],usegmt=True)
    ElementTree(rss).write(out/'feed.xml',encoding='utf-8',xml_declaration=True)
    print(json.dumps({'news':len(items),'sources':states,'ai_status':snapshot['briefing']['status'],'curation':curation},ensure_ascii=False))
    if not items:
        raise RuntimeError('No live or cached news; refusing to publish an empty snapshot')
    return snapshot


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=ROOT/'frontend/public/data');p.add_argument('--previous',type=Path);p.add_argument('--ai',action='store_true');args=p.parse_args()
    collect(args.output,args.previous,args.ai)
