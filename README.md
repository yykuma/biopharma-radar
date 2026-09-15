# BioPharma Radar

Professional biopharma news, prioritizing US-listed companies with partial Hong Kong coverage. The frontend reuses [Fusion](https://github.com/0x2E/fusion)
at `1f99b1fc654baa0108e4df4577429d62d0e53cb8`. The pipeline imports RSSFetcher from [TrendRadar](https://github.com/sansan0/TrendRadar)
at `792bcc3928b1617bba09df34989fd5675c159b86`.

## Architecture

GitHub Actions collects news every two hours, exports static JSON, and builds Fusion for
Cloudflare Pages. No separate Fusion Go server or database is required.
Sources are BioPharma Dive and the Fierce Biotech Biotech section.
The former Google, Yahoo, wire feeds and single-company feed are retired; their
articles are removed from current snapshots. Source changes clear cached briefing
text while preserving AI quota, cooldown and rotation state.
The previous published snapshot retains up to 1,500 articles for 30 days and AI routing
state. Bookmarks and read status are browser-local. Sources are maintained in Git.

Market labels are heuristic and incomplete. Unknown companies remain global.
The industry group includes unidentified companies and other listing markets. Content consists of
headlines and short source excerpts, not mirrored full articles. All source links remain.

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
`news_summary` participate. These cost labels are operator declarations, not billing
verification. Keep paid billing and automatic top-ups disabled.

`round_robin` advances after the last successful model; `failover` preserves order.
Each run allows at most three requests, without SDK retries or paid fallback.
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
