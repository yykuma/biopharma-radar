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
The previous published snapshot retains up to 5,000 articles for 90 days and AI routing
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
`TYPESAFE_API_KEY`, `AMD_API_KEY`, `MISTRAL_API_KEY`, `GLM_API_KEY`, `SENSENOVA_API_KEY`, `AGNES_API_KEY`, `OPENROUTER_API_KEY`. Individual models may override `key_env`.
The integration supports OpenAI-compatible chat completions and TypeSafe System One editorial decisions, both through the shared routing session.

Providers/models have separate enable switches. Models are classified by `category`,
`free_tier` and supported `tasks`. Only enabled free/limited_free/beta_free models supporting
the requested task (`news_summary`, `news_curation` or `news_translation`) participate. These cost labels are operator declarations, not billing
verification. Keep paid billing and automatic top-ups disabled.

Translation and briefing use ordered `failover`: AMD `DeepSeek-V4-Flash-0731` → `Qwen3.8-Flash-Next` → `GLM-5.3-Flash` → SenseNova `deepseek-v4-flash`. Each request starts at the first eligible model. Earlier successes do not reorder this chain. Busy or paced AMD requests wait for their slot instead of letting another supplier bypass them. Models in persistent cooldown are temporarily ineligible.
Task requests have no fixed attempt-count limit. Each eligible model is tried at most once per request, without SDK retries or paid fallback; later requests can retry after cooldown. Translation, classification and briefing share concurrency limits, cooldowns and usage counters. Secondary suppliers are disabled but retain their connection settings. Only OpenRouter has a configured application cap: 50 reserved requests per UTC day, retained for any future re-enablement.
AMD and SenseNova each have at least 30 seconds between request starts across tasks in the shared session, controlled by `execution.supplier_min_interval_seconds`. Requests do not overlap within a supplier. A slow request can make the actual interval longer than 30 seconds.
429 honors Retry-After when supplied, otherwise waits an hour. AMD cools only the affected model and rotates; other providers cool the supplier. 401/403 cool the supplier for 24 hours. A 404 cools the model
for 24 hours; other failures for 15 minutes. Cooldowns and rotation position persist
in the published briefing without credentials or raw exception messages.

Up to 20 news records and 700 output tokens per summary; at most one successful
summary every six hours. Identical input is reused. Failure preserves the last
summary while news publishing continues. AMD GLM-5.3-Flash is enabled, but its initial inference probe timed out; catalog availability is not proof of inference reliability. SenseNova uses only `deepseek-v4-flash` in its general pool; native SenseNova models are disabled.

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
`routing_role: fallback` applies to the optional round-robin strategy. Production ordered failover follows registry order; Mistral, Agnes and OpenRouter are currently disabled.
OpenRouter has a 50-request daily cap; all other providers and models have no daily application cap. SenseNova retains a pricing review deadline.
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

Reviewed Chinese translations are stored in `config/editorial-translations.json`.
The September 16, 2026 backlog pass adds 117 translations completed or reviewed
by Codex Astra at low reasoning effort, with per-record model provenance.
A follow-up pass reviewed the remaining 48 automatic translations, corrected 47
(including removal of boilerplate), and cached all 48 with review timestamps.
The 60 previously reviewed seed records were left unchanged.
A source fingerprint prevents reuse after source text changes. Untranslated articles are processed in up to six sequential batches of four per
collection run (24 articles maximum), with a 3,000-token output ceiling per batch.
Older unattempted articles come first. Failed batches stop that run and retain an
attempt timestamp so they do not indefinitely block other pending articles. Translation fetches only bounded
public introductions on configured HTTPS hosts, rejects redirects, and falls back
to RSS excerpts without bypassing access controls. Full source bodies are transient
and are not exported. Invalid JSON, mismatched IDs and truncated responses remain
pending for later runs. API failure does not block original news publication.
The original title/excerpt remain available; Chinese fields are additive.

## Editorial grouping and source expansion

The feed configuration also includes Drugs.com clinical results, approvals and
applications; BioSpace drug development, FDA and deals; and Fierce Pharma. Source
health is measured on the GitHub runner, independently of a reader's network.
Drugs.com attribution uses its required feed names; source links are retained.

Tracking parameters are removed before URL identity is computed; meaningful
query parameters remain. Existing tracked URLs migrate to canonical IDs, so a
previously read/bookmarked tracked URL may have a new ID. Same-event coverage
is grouped without removing original JSON records. Exact syndication can group
without AI; semantic grouping requires a high-confidence model reference, a
seven-day window and compatible company matches. Later developments must remain
separate. Group IDs are snapshot-local.

Editorial classification processes at most two batches of 24 records per run,
sharing translation/briefing concurrency limits and cooldowns. Responses are
validated and cached against source text. Pending/uncertain stories stay visible.
Only high-confidence pure publicity is hidden by default, with a reader toggle.
Company announcements, commercialization, sales and licensing are not publicity
by default. JSON keeps every record; RSS and briefings use one non-marketing
representative per event. Company/market filters run before reader grouping, and
read actions apply to the currently retained reports in an event. New reports
remain unread. Saved bookmarks remain individually accessible.

## Bounded parallel AI execution

Ordered failover runs translation before classification in one editorial worker. The optional round-robin strategy can run both tasks concurrently when two primary suppliers are available.
A shared routing session atomically reserves supplier slots before dispatch, enforces a global ceiling of two requests and one per supplier, and persists token usage and cooldowns. Ordered failover waits for the preferred model instead of bypassing it when busy or paced. No duplicate speculative requests are sent.
Editorial decisions prefer TypeSafe Jev, then AMD and SenseNova DeepSeek; translation and briefing use AMD and SenseNova only. Provider review deadlines and free-only model selection remain enforced.
Briefing generation starts after both tasks finish so it uses completed labels
and translations. Briefing uses the same routing session. The public curation.execution report records sanitized
attempts and observed concurrency; zero means no eligible request was dispatched.

## Operator tuning (one configuration file)

Edit `config/ai-providers.json`; credentials remain in GitHub Actions Secrets.
Changes take effect on the next collection run after deployment. The current
profile uses one editorial worker with ordered failover and one request per supplier.

| Setting | Current value | Meaning |
| --- | --- | --- |
| `execution.max_parallel_requests` | 2 | Total in-flight ceiling; ordered failover currently uses one editorial worker |
| `execution.supplier_concurrency` | 1 per supplier | Shared supplier slot limit, including models and quota pools |
| `execution.supplier_min_interval_seconds` | AMD/SenseNova: 30 each | Minimum interval between request starts per supplier |
| `translation.batch_size` | 4 | Articles per translation request |
| `translation.max_batches_per_run` | 6 | Sequential batches per collection, at most 24 articles |
| `translation.max_output_tokens` | 3000 | Response ceiling per translation batch |
| `curation.batch_size` | 24 | Articles per classification request |
| `curation.max_batches_per_run` | 2 | Classification batches per collection |
| `curation.max_output_tokens` | 3600 | Response ceiling per classification batch |
| `execution.task_order` | translation, curation | Task order in ordered failover mode |
| `providers[].rate_limit_scope` | AMD: model; others: supplier | Scope paused after a 429; authentication failures always pause the supplier |
| `providers[].enabled` / `models[].enabled` | Per entry | Enable/disable a provider or model |
| `providers[].routing_role` | Mistral/Agnes: fallback | Used only by round-robin strategy; both providers currently disabled |

These are application ceilings, not purchased or guaranteed provider allowances.
Increasing the workload does not reset provider cooldowns or usage counters.
Keep each supplier at one request unless a later explicit change is intended.
Translation stops after an unsuccessful batch; other pending articles get a
chance on a later run. Successful text is never regenerated without a source
change. Raise output tokens alongside batch size if needed, and keep batches
within the job's 15-minute execution window.

Validate after an edit: `python -c 'from pipeline.ai_router import load_registry; load_registry(); print("AI settings valid")'`.
Run `python -m unittest discover -s pipeline -p 'test_*.py'` before publishing.
Check `data/latest.json` → `curation.translation` for completed/pending counts,
and `curation.execution` for attempts, actual parallelism and supplier peaks.

## Incremental feed checks

RSS readers poll the current feed window; most publishers do not expose a
resumable historical cursor. Each source now persists its ETag/Last-Modified
validators. When a publisher returns HTTP 304, the pipeline skips body parsing
and reuses retained articles. HTTP 200 responses are parsed using TrendRadar;
canonical URL identity and source fingerprints avoid repeated AI work. Publishers
without validators still require a small RSS download. Changing a feed URL, item
limit or retention horizon invalidates validators and forces a fresh request.
Source state exposes HTTP status, response bytes, and new/updated article counts.
The previous published JSON is the restart checkpoint for articles and AI state.
Retention is 90 days and at most 5,000 original reports.

## Agnes AI integration

`agnes-2.5-flash` uses the official OpenAI-compatible base URL `https://apihub.agnes-ai.com/v1`. Its current input, cached-input and output prices were verified as zero on 2026-09-15 at https://www.agnes-ai.com/en/docs/pricing. The promotion has no published fixed end date; the registry expiry is a local review deadline. Only this model is configured for Agnes; the supplier is currently disabled after unreliable structured translation results. Credentials use the `AGNES_API_KEY` Actions secret. Agnes shares the global concurrency ceiling, keeps one in-flight request, and has no daily application cap. Translation, classification and briefing use the same router.

## OpenRouter free routing and durable counter

`inclusionai/ling-3.0-flash-vl:free` is enabled for `news_curation` and `news_summary`, with one in-flight request. It is excluded from `news_translation`. Classification of eight articles and a Chinese briefing passed live tests on 2026-09-15. The provider remains subject to its own free-tier limits: https://openrouter.ai/docs/api-reference/limits.

Every inference attempt reserves one request before sending, including attempts that fail or are cancelled. The 50-request cap is shared across all OpenRouter models and tasks in this application. UTC midnight resets the counter (08:00 Asia/Singapore). No paid model is configured as fallback.

The ledger is `state/openrouter-quota.json` on the `codex/ai-state` branch. Create that branch from `main` before the first call. GitHub Actions supplies its automatic `GITHUB_TOKEN` as `QUOTA_GITHUB_TOKEN`, with `contents: write` permission. Compare-and-swap writes prevent concurrent runs from exceeding the cap; a failed ledger read/write blocks OpenRouter and permits other suppliers. Counts survive failed publishing, cancellation and redeployment. The state branch does not trigger the main publishing workflow. The ledger contains counts and dates, never API keys. External clients using the same OpenRouter account are outside this application's counter.

`curation.execution.quota_counters.openrouter` publishes the last observed count and reset time, also shown in the briefing dialog. This is a collection-time snapshot, not a live account balance.

## Dedicated translation direction

Pure translation of existing titles and excerpts should use a dedicated translation API with batching and source-fingerprint caching. Summarization from longer source text, editorial classification and event matching remain LLM tasks. Task capabilities are separate so providers can be enabled for editorial work without receiving translation requests. Existing LLM localization remains active until a dedicated service is configured and verified; no replacement translation credentials have been installed yet.

Tencent Cloud text translation currently advertises 5 million free characters per month and defaults postpaid billing to off: https://cloud.tencent.cn/document/product/551/35017. Keep postpaid off for stop-at-quota behavior. No Tencent service is enabled by this repository change.

Briefings request structured text/source-number pairs. The renderer adds citations from those source numbers and publishes only the cited links, so changing summary order does not renumber the underlying news. Unknown source numbers and unstructured output fail validation. Format version changes trigger regeneration of older cached briefings. Semantic faithfulness still depends on model output and requires source checks.

## Independent AI retries

The publication workflow accepts `ai_only=true`. This mode reads the latest
published snapshot, resumes translation/classification/briefing, and preserves
RSS check times without fetching feeds again. Pending articles remain the queue.
A separate wake-up job waits until the earliest eligible model cooldown expires
and dispatches the next AI-only run using the repository's `GITHUB_TOKEN` with
`actions: write`. It does not depend on the RSS cron and does not hold the
publication concurrency lock. Each wake-up waits at most one hour before
rechecking; healthy backlog continues after a two-minute minimum delay. A newer
wake-up replaces an older one, and the chain stops when no work remains or no
configured model can serve it. GitHub runner queues can still add latency.

Cooldowns and pending translation attempt times are checkpointed without secrets
in `state/ai-router.json` on `codex/ai-state`. AI-only runs deploy only when reader
content changes; failed requests do not consume Pages deployments. This uses
standard GitHub-hosted runners in the public repository; private repositories
would have a different Actions minute allowance. Regular collection remains a
fallback if a workflow is cancelled or fails before scheduling its successor.

## TypeSafe editorial decisions

Jev `jev-1.13.0` is the first route for `news_curation` only: category selection
(including marketing) and same-event matching. It uses `/v1/systemone`, with
typed questions and deterministic mapping back to article IDs. Classification
requires confidence and selected-option probability of at least 0.90; event
matching requires 0.95. Both thresholds live in the model registry. Uncertain
classifications remain visible, and uncertain event matches remain separate.
Existing company/date grouping checks still apply.

Errors, timeouts, malformed responses, or a removed model use the existing
cooldowns and fall back to the ordered AMD models, then SenseNova DeepSeek.
Translation and text summaries never use Jev. Its provider enable switch and
`TYPESAFE_API_KEY` Actions secret are independent. Free access is the operator's
account-specific declaration on 2026-09-19, not the vendor's public list price.
No daily application cap is added. Existing editorial results stay cached; newly
arriving or changed articles use this route.
