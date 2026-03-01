# Coke ON Analytics POC — Project Scope
## Handover Document for Claude Code

---

## Overview

Build a text-based analytics query interface that allows users to ask natural language questions about Coke ON user, sales, and behavioural data — including both **descriptive analytics** (historical reporting) and **predictive / recommendation** queries (seasonal demand forecasting, churn detection, campaign prioritisation, machine recovery potential).

Queries are sent to an n8n webhook, processed by an n8n AI agent, and answered by querying a synthetic Supabase (PostgreSQL) database via its MCP tool.

The interface and agent responses must support both **English and Japanese**. Supabase tables are pre-populated by importing CSV files — neither n8n nor the application needs write access.

---

## Architecture

```
User (text input — English or Japanese)
      ↓
  Frontend UI (text query form)
      ↓
  n8n Webhook (POST endpoint)
      ↓
  n8n AI Agent (LLM-powered, bilingual)
      ↓
  Supabase MCP Tool (read-only SQL queries)
      ↓
  Supabase / PostgreSQL (pre-loaded synthetic data — CSV import)
      ↓
  Response returned to UI (in query language)
```

**Why pre-computed tables?** The pre-aggregated tables (`machines`, `user_metrics`, `campaign_segment_performance`) are kept for query performance and simplicity. Supabase supports SQL JOINs, so these could also be expressed as views over the raw tables — but as pre-loaded tables they give the agent direct access to derived signals without complex SQL at query time.

---

## Components

### 1. Frontend (Text Query Interface)
- Single-page web app (plain HTML/CSS/JS — no build step)
- Text input field accepting queries in English or Japanese
- Language toggle (EN / JA) to switch UI labels, placeholder text, and response language
- Font stack supports Japanese characters (Noto Sans JP via Google Fonts)
- Submit button to POST query to the n8n webhook URL (configured in `frontend/config.js`)
- Response display area (rendered text with basic markdown table support)
- Loading/pending state while awaiting response
- No authentication required for POC

### 2. n8n Workflow
- **Webhook node**: Accepts POST requests with a `query` field and optional `language` field (JSON body)
- **AI Agent node**: Receives the query, uses an LLM to interpret intent and call the Supabase MCP tool via `execute_sql`; responds in the same language as the query
- **Response node**: Returns `{ "answer": "..." }` with HTTP 200
- The agent system prompt includes full schema context for all 6 tables and SQL query patterns for each analytic type

### 3. Supabase Database (Synthetic Data)
Six PostgreSQL tables created via `data/schema.sql` and populated by CSV import. **No write operations are needed from the application or n8n** — the MCP tool is used read-only.

#### `users` table — raw data
| Field | Type | Notes |
|---|---|---|
| user_id | text | Unique identifier |
| join_date | date | For new user segmentation |
| age | integer | For age group analysis |
| gender | text | Male / Female / Other |
| region | text | Japanese prefecture |

#### `sales` table — raw data
| Field | Type | Notes |
|---|---|---|
| sale_id | text | Unique identifier |
| user_id | text | Foreign key → users |
| sku | text | Georgia Coffee / Coca-Cola / Water / Fanta / Aquarius |
| purchase_date | date | Seasonally weighted distribution |
| machine_id | text | Vending machine identifier |
| machine_location | text | Prefecture |

#### `app_interactions` table — raw data
| Field | Type | Notes |
|---|---|---|
| interaction_id | text | Unique identifier |
| user_id | text | Foreign key → users |
| event_type | text | LoggedIn / EarnedStamp / EngagedCampaign |
| campaign_id | text | Populated when event_type = EngagedCampaign |
| campaign_name | text | Human-readable campaign name |
| event_date | date | |

#### `machines` table — context data
| Field | Type | Notes |
|---|---|---|
| machine_id | text | Unique identifier |
| location | text | Prefecture |
| area_type | text | Transit Hub / Office District / Residential / Tourist / University / Retail |
| footfall_tier | text | High / Medium / Low |
| footfall_index | integer | Relative pedestrian volume, 1–100 |

#### `user_metrics` table — pre-computed per user
| Field | Type | Notes |
|---|---|---|
| user_id | text | Foreign key → users |
| last_purchase_date | date | |
| days_since_last_purchase | integer | |
| total_purchases | integer | |
| purchases_30d | integer | Purchases in last 30 days |
| purchases_90d | integer | Purchases in last 90 days |
| avg_days_between_purchases | numeric | |
| churn_risk_score | numeric | 0–100 composite score |
| churn_risk_tier | text | High (≥70) / Medium (40–69) / Low (<40) |

#### `campaign_segment_performance` table — pre-aggregated
| Field | Type | Notes |
|---|---|---|
| campaign_id | text | |
| campaign_name | text | |
| age_group | text | 18-24 / 25-34 / 35-44 / 45-54 / 55-65 |
| gender | text | Male / Female / Other |
| quarter | text | Format: YYYY-QN (e.g. 2025-Q3) |
| engagement_count | integer | Total engagement events |
| unique_users | integer | Distinct users who engaged |
| engagement_rate | numeric | unique_users / segment size |

**Synthetic data targets** (generated by `data/generate_data.py` and imported to Supabase):
- ~500 users
- ~5,000 sales records spanning the last 6 months (seasonally weighted SKU distribution)
- ~3,000 app interaction records spanning the last 6 months
- 50 machines with footfall context (6 designated as high-footfall / low-sales recovery candidates)
- 500 user metrics rows (one per user, pre-computed from sales data)
- ~360 campaign segment performance rows (8 campaigns × 5 age groups × 3 genders × 3 quarters)

---

## Target Questions / Insights

The agent should be capable of answering the following in both English and Japanese.

### User Intelligence
- What is the current breakdown of the Coke ON user funnel?
  - New users (joined in last 30 days)
  - MAU (purchased or interacted in last 30 days)
  - Monthly+ (purchased in last 30 days, or avg. every 30 days over last 6 months)
  - Weekly+ / Daily+ purchasers
- Month-on-month aggregate of each segment for the past 6 months (tabular output)

### Sales Insights
- Month-to-month sales volume for Georgia Coffee
- Top 10 vending machines by sales volume
- Which time period or user segment has the highest water purchase propensity
- Any notable sales spikes by location

### App Interaction Insights
- Most popular campaigns in the last 6 months
- Top 10 campaigns by age group
- Top 10 campaigns by gender

### Predictive & Recommendation Insights
- **Seasonal demand forecast**: "Predict the most popular drinks in Kyoto this August" — agent retrieves monthly SKU × location sales history, identifies seasonal trend, projects forward
- **Machine recovery potential**: "Which underperforming vending machines have the highest recovery potential based on footfall?" — agent JOINs sales counts per machine with machines.footfall_index to identify high-opportunity gaps
- **Churn detection & intervention**: "Which user segments are showing early churn signals and what's the recommended intervention?" — agent queries user_metrics for High churn_risk_tier users, segments by age/gender/region, recommends highest-engagement_rate campaigns from campaign_segment_performance
- **Campaign prioritisation by segment**: "Which campaigns should we prioritise for 25–34 female users in Q3?" — agent queries campaign_segment_performance filtered by age_group + gender + quarter, ranks by engagement_rate

---

## Acceptance Criteria

- [ ] User can type a natural language question in English or Japanese and receive a relevant, data-backed answer in the same language
- [ ] UI renders correctly with Japanese characters
- [ ] n8n webhook accepts POST requests and returns structured responses
- [ ] AI agent correctly routes queries to Supabase via MCP (read-only SQL) and interprets results
- [ ] Supabase MCP tool is used read-only — no INSERT, UPDATE, DELETE, or DDL operations
- [ ] All analytic target questions listed above return a coherent answer in both languages
- [ ] All four predictive / recommendation queries return a coherent, data-backed answer in both languages
- [ ] UI handles loading states and basic error responses gracefully

---

## Out of Scope (POC)

- Voice input
- User authentication
- Real production data (synthetic only)
- Writing to or updating Supabase tables from the app or n8n
- Deployment / hosting (localhost is fine)
- Advanced data visualisation (plain text / simple tables are sufficient)
- Real-time user_metrics refresh (pre-computed at CSV generation time)

---

## Suggested Implementation Order

1. Run `python3 data/generate_data.py` to produce all 6 CSV files and `schema.sql`
2. Run `schema.sql` in the Supabase SQL Editor to create the tables
3. Import the 6 CSVs via Supabase Table Editor
4. Start the local Supabase MCP server: `npx @supabase/mcp-server-supabase@latest --port 3000`
5. Import `n8n/workflow.json` and wire the LLM credential
6. Test the webhook end-to-end with sample analytic and predictive queries
7. Open `frontend/index.html` in a browser and verify the full flow

---

## Config

All frontend config lives in `frontend/config.js`:
- `WEBHOOK_URL` — the n8n POST endpoint (default: `http://localhost:5678/webhook/coke-on-query`)

n8n credentials (set in n8n UI, not in files):
- LLM API key (any provider; workflow ships with OpenAI/GPT-4o sub-node — swap as needed)

Supabase MCP server (environment variables when starting the server process):
- `SUPABASE_URL` — your cloud Supabase project URL
- `SUPABASE_KEY` — your service_role key (read-only operations only from the agent)

---

## Notes

- The n8n agent system prompt is seeded with full schema context for all 6 tables, funnel definitions, and SQL query patterns for each analytic type
- Sales data includes realistic seasonal SKU weighting (summer → Water/Fanta; winter → Georgia Coffee) to give the LLM meaningful patterns to extrapolate from
- Six machines are deliberately assigned high footfall_index but low sales volume to serve as clear recovery-opportunity examples
- Supabase MCP's `execute_sql` tool allows the agent to write arbitrary SQL — JOINs, GROUP BY, and ORDER BY are all available
- Use a service_role key scoped to read-only operations; the agent system prompt explicitly instructs against any write SQL
