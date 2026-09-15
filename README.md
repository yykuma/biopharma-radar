# BioPharma Radar

Professional biopharma news, prioritizing US-listed companies with partial Hong Kong coverage. The frontend reuses [Fusion](https://github.com/0x2E/fusion)
at `1f99b1fc654baa0108e4df4577429d62d0e53cb8`. The pipeline imports RSSFetcher from [TrendRadar](https://github.com/sansan0/TrendRadar)
at `792bcc3928b1617bba09df34989fd5675c159b86`.

## Architecture

GitHub Actions collects news every two hours, exports static JSON, and builds Fusion for
Cloudflare Pages. No separate Fusion Go server or database is required.
Sources are BioPharma Dive, the Fierce Biotech Biotech section, and official releases from Lilly, Amgen, Regeneron and Vertex.
The former Google, Yahoo and wire feeds are retired; their
articles are removed from current snapshots. Source changes clear cached briefing
text while preserving AI quota, cooldown and rotation state.
The previous published snapshot retains up to 1,500 articles for 30 days and AI routing
state. Bookmarks and read status are browser-local. Sources are maintained in Git.

Market labels are heuristic and incomplete. Unknown companies remain global.
The industry group includes unidentified companies and other listing markets. Content includes original headlines/excerpts plus Chinese editorial or AI summaries. Full articles are not mirrored. All source links remain.

## Development

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python pipeline/collect.py
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

Build with `pnpm build`. Hash navigation supports Cloudflare Pages deep links.

## Public interface

`data/latest.json`, `data/briefing.json`, `data/markets/{us,hk,global}.json`, and
`data/feed.xml` are static GET resources. Consumers filter downloaded records locally;
query strings do not filter responses. See `openapi.json` and `llms.txt`.
All timestamps are Unix seconds. Null `published_at` means unknown publication time;
`first_seen_at` is discovery time. Check `last_success_at` and `collection_status`.
The A-share data endpoint is retired. One article can belong to multiple markets. Schema version: `1.0`.
`publisher` is the display source, independent of the collection channel name.
The sidebar merges channels from the same publisher within each market.
`content_type` is `brief` for wire/flash feeds and `news` for reporting and company
press-release feeds; `content_type_basis` is `source_format`. Missing excerpts do
not turn news into briefs. These fields also apply to retained articles on refresh.

## Adding and rotating AI APIs

Edit `config/ai-providers.json`. Credentials must never be stored in this file.
Add a GitHub Actions secret and map it into the workflow environment. Existing names:
`AMD_API_KEY`, `MISTRAL_API_KEY`, `GLM_API_KEY`, `SENSENOVA_API_KEY`. Individual models may override `key_env`.
The integration currently supports OpenAI-compatible chat completions with usage and completion-status tracking.

Providers/models have separate enable switches. Models are classified by `category`,
`free_tier` and supported `tasks`. Only enabled free/limited_free/beta_free models supporting
the requested task (`news_summary` or `news_translation`) participate. These cost labels are operator declarations, not billing
verification. Keep paid billing and automatic top-ups disabled.

`round_robin` advances after the last successful model; `failover` preserves order.
Each task allows at most three attempts, without SDK retries or paid fallback. Translation and briefing share provider daily request caps, cooldowns and usage counters.
429 cools the entire provider for an hour; 401/403 for 24 hours. A 404 cools the model
for 24 hours; other failures for 15 minutes. Cooldowns and rotation position persist
in the published briefing without credentials or raw exception messages.

Up to 20 news records and 700 output tokens per summary; at most one successful
summary every six hours. Identical input is reused. Failure preserves the last
summary while news publishing continues. Untested Qwen and GLM models stay disabled.

## Free hosting limitations

Use a public repository with a standard GitHub runner. Prebuilt assets are uploaded to Cloudflare Pages.
A two-hour schedule stays below 500 deployments per month with room for fixes.
Configure repository variables `SITE_URL` and `CLOUDFLARE_PROJECT_NAME`, and
secrets `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` (Pages Edit only).
The workflow stays inactive until `SITE_URL` is configured. Scheduled jobs may be delayed
or dropped. GitHub disables schedules after 60 days without repository activity.
The UI displays the last collection time. If collection/deployment fails, the last
published website remains available. Free API availability can change.

## Verification and licensing

Run `python -m unittest discover -s pipeline -p 'test_*.py'`, then in `frontend`
run `pnpm exec tsr generate`, `pnpm exec tsc -b --noEmit` and `pnpm build`.
Fusion's MIT notice is preserved in LICENSE. The Python pipeline is GPL-3.0
(see pipeline/LICENSE), integrating the pinned GPL-3.0 TrendRadar dependency.
The static frontend is MIT. News content remains owned by its respective sources.

## Quota pools and review dates

A registry entry represents one routing and cooldown pool. SenseNova has separate
Flash and general entries sharing one secret. Its Flash pool can spill into general
credits upstream; local token counters cannot reveal account credit balances.
`token_usage` records only reported tokens consumed by this application, including
truncated responses. It excludes other clients and requests with unknown usage.
`max_requests_per_day` counts every attempt, resets at UTC midnight, and is scoped
to a pool or model. `expires_at` is a local review deadline, not a provider promise.
`routing_role: fallback` reserves limited APIs for primary-provider failures.
SenseNova defaults to two attempts per pool per day and a 30-day pricing review.
Quota descriptions are operator notes, not a hard guarantee about provider billing.

## Company catalog and Chinese news

`config/companies.json` is the reviewed initial catalog: 690 US listings and 82 HK
listings, consolidated to 768 issuers. Four issuers have both markets. This is
source-based coverage, not an assertion that every currently listed company is
present. OTC companies, devices and hospitals are outside the US category scope.
Each entry retains classification/listing sources and a verification date.
`config/company-overrides.json` supplies reviewed aliases, Chinese names and HK
coverage. `pipeline/build_companies.py INPUT_DIR --date YYYY-MM-DD` rebuilds the
catalog from downloaded source files; review additions and removals before commit.
Input names and URL patterns are documented in the script. The HK rows input is
an array of spreadsheet rows from HKEX ListOfSecurities.xlsx. Industry source
files are StockAnalysis biotechnology pages 1/2 and general/specialty drug pages;
listing files are Nasdaq Trader nasdaqlisted.txt and otherlisted.txt.

The pipeline exports `data/companies.json` and `data/companies/{company_id}.json`.
Company filters combine with market, unread and bookmark filters. News counts
represent retained articles, not total market news. Official source IDs indicate
which company feeds are connected; a catalog entry does not enable collection.

The first 52 articles have reviewed Chinese translations in
`config/editorial-translations.json`. A source fingerprint prevents reuse after
source text changes. New untranslated articles form a batch of at most four per
collection run, with a 3,000-token output ceiling. Translation fetches only bounded
public introductions on configured HTTPS hosts, rejects redirects, and falls back
to RSS excerpts without bypassing access controls. Full source bodies are transient
and are not exported. Invalid JSON, mismatched IDs and truncated responses remain
pending for later runs. API failure does not block original news publication.
The original title/excerpt remain available; Chinese fields are additive.
