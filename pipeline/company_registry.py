"""Resolve news to the reviewed company registry, independently of publishers."""
import json
import re
from pathlib import Path

CATALOG = json.loads((Path(__file__).resolve().parents[1]/'config/companies.json').read_text())
COMPANIES = CATALOG['companies']
BY_ID = {c['id']:c for c in COMPANIES}


def alias_pattern(alias):
    return re.compile(r'(?<![\w])'+re.escape(alias)+r'(?![\w])', re.I) if alias.isascii() else re.compile(re.escape(alias),re.I)


MATCHERS = [(c, [alias_pattern(a) for a in c['aliases'] if len(a)>=3],
             [alias_pattern(a) for a in c.get('exclude_aliases',[])]) for c in COMPANIES]


def match_companies(title, source):
    found = set(source.get('company_ids',[])) & BY_ID.keys()
    for company, aliases, exclusions in MATCHERS:
        text = title
        for excluded in exclusions:
            text = excluded.sub('',text)
        if any(p.search(text) for p in aliases):
            found.add(company['id'])
        for listing in company['listings']:
            ticker = re.escape(listing['ticker'])
            pattern = (rf'\b0*{int(listing["ticker"])}\.HK\b' if listing['market']=='HK'
                       else rf'(?:\${ticker}\b|\b(?:NASDAQ|NYSE|NYSE American)\s*:\s*{ticker}\b)')
            if re.search(pattern, text, re.I):
                found.add(company['id'])
    return [BY_ID[id] for id in sorted(found)]
