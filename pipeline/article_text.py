"""Read bounded public article introductions from explicitly configured hosts."""
import json
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from bs4 import BeautifulSoup

USER_AGENT='BioPharmaRadar/1.0 (+https://github.com/yykuma/biopharma-radar)'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def extract(document, selector):
    soup=BeautifulSoup(document,'html.parser')
    container=soup.select_one(selector)
    text=''
    if container:
        paragraphs=[p.get_text(' ',strip=True) for p in container.select('p, li')]
        text='\n'.join(p for p in paragraphs if len(p)>45)[:7000]
    published=None
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            data=json.loads(node.get_text())
            entries=data if isinstance(data,list) else data.get('@graph',[data])
            if isinstance(entries,dict):entries=[entries]
            for entry in entries:
                if entry.get('@type') in ('NewsArticle','Article'):
                    published=entry.get('datePublished') or published
        except (ValueError,TypeError,AttributeError):
            continue
    return text,published


def fetch_text(article, source):
    parsed=urlsplit(article['url'])
    if (parsed.scheme!='https' or parsed.hostname not in source.get('article_hosts',[])
        or parsed.username or parsed.password or parsed.port not in (None,443)):
        return '',None
    request=Request(article['url'],headers={'User-Agent':USER_AGENT})
    with build_opener(NoRedirect).open(request,timeout=12) as response:
        document=response.read(1_200_001)
        if len(document)>1_200_000:raise ValueError('Article exceeds size limit')
    return extract(document,source['article_selector'])
