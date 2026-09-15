"""Rebuild the reviewed registry from locally downloaded, public source files.

Inputs are deliberately explicit: a source/schema change must be reviewed before
it changes the company universe. No stock prices or full vendor tables are kept.
"""
import argparse
import csv
import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDUSTRIES = {
    'us-bio': ('biotechnology', 'biotechnology'),
    'us-bio-2': ('biotechnology', 'biotechnology'),
    'us-pharma': ('pharmaceuticals', 'drug-manufacturers-general'),
    'us-specialty': ('pharmaceuticals', 'drug-manufacturers-specialty-and-generic'),
}


def build(directory, checked_at):
    listings = {}
    for filename in ('nasdaqlisted', 'otherlisted'):
        for row in csv.DictReader((directory / filename).read_text().splitlines(), delimiter='|'):
            symbol = row.get('Symbol') or row.get('ACT Symbol')
            if row.get('Test Issue') != 'N' or row.get('ETF') != 'N':
                continue
            exchange = 'NASDAQ' if filename == 'nasdaqlisted' else {'N':'NYSE', 'A':'NYSE American', 'P':'NYSE Arca'}.get(row['Exchange'])
            if exchange:
                listings[symbol] = {'market':'US', 'ticker':symbol, 'exchange':exchange,
                    'source_url':f'https://www.nasdaqtrader.com/dynamic/SymDir/{filename}.txt'}
    companies = {}
    for filename, (category, slug) in INDUSTRIES.items():
        rows = re.findall(r'\{no:\d+,s:("(?:\\.|[^"\\])*"),n:("(?:\\.|[^"\\])*")', (directory / filename).read_text())
        if not rows:
            raise ValueError(f'No company rows: {filename}')
        for raw_symbol, raw_name in rows:
            symbol, name = json.loads(raw_symbol), html.unescape(json.loads(raw_name))
            if symbol not in listings:
                continue
            short = re.sub(r',?\s+(?:Inc\.?|Incorporated|Corporation|Corp\.?|Limited|Ltd\.?|plc|SE|S\.A\.)$', '', name, flags=re.I).strip(' ,')
            companies['us-'+symbol.lower()] = {'id':'us-'+symbol.lower(), 'name':name,
                'category':category, 'aliases':list(dict.fromkeys([name, short])),
                'listings':[listings[symbol]], 'classification_source':f'https://stockanalysis.com/stocks/industry/{slug}/',
                'verified_at':checked_at}
    hk_rows = json.loads((directory/'hk-rows.json').read_text())
    hk = {r[0]:r for r in hk_rows[3:] if len(r)>2 and r[2]=='Equity' and r[0].isdigit() and int(r[0])<10000}
    overrides = json.loads((ROOT/'config/company-overrides.json').read_text())
    for entry in overrides:
        target = entry.get('us_ticker')
        company = companies.get('us-'+target.lower()) if target else None
        code = entry.get('hk_ticker')
        if code and code not in hk:
            raise ValueError(f'Review missing HK listing: {code}')
        if target and company is None:
            raise ValueError(f'Review missing US listing: {target}')
        if company is None:
            company = {'id':'hk-'+code, 'name':entry['name'], 'aliases':[], 'listings':[],
                'category':entry.get('category','pharmaceuticals'), 'classification_source':'editorial_review', 'verified_at':checked_at}
            companies[company['id']] = company
        if code:
            company['listings'].append({'market':'HK','ticker':code,'exchange':'HKEX','security_name':hk[code][1],
                'source_url':'https://www.hkex.com.hk/eng/services/trading/securities/securitieslists/ListOfSecurities.xlsx'})
        company['name_zh'] = entry['name_zh']
        company['aliases'] = list(dict.fromkeys(company['aliases'] + entry.get('aliases',[]) + [entry['name_zh']]))
        if entry.get('exclude_aliases'):
            company['exclude_aliases'] = entry['exclude_aliases']
    records = sorted(companies.values(), key=lambda c:c['id'])
    return {'schema_version':'1.0','verified_at':checked_at,
        'coverage':{'US':'Biotechnology and drug manufacturers in the source industry lists, cross-checked against Nasdaq Trader listings. Excludes OTC, devices, hospitals and most research service firms. Not a guarantee of exhaustive or real-time coverage.',
                    'HK':'Reviewed initial pharmaceutical/biotechnology/CRO subset, cross-checked against the HKEX securities list. Not the complete healthcare sector.'},
        'companies':records}


if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('directory',type=Path); parser.add_argument('--date',required=True)
    args=parser.parse_args(); data=build(args.directory,args.date)
    (ROOT/'config/companies.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'companies':len(data['companies']), **{m:sum(any(l['market']==m for l in c['listings']) for c in data['companies']) for m in ('US','HK')}}))
