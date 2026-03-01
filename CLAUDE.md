# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Coke ON Analytics POC — a bilingual (EN/JA) natural language analytics interface. Users ask questions in English or Japanese → frontend POSTs to an n8n webhook → AI agent queries Supabase via MCP → answer returned. See `coke-on-poc-scope.md` for full requirements and `SETUP.md` for wiring instructions.

## Commands

**Regenerate all CSV data and schema:**
```bash
cd data && python3 generate_data.py
```
Outputs 6 CSV files and `schema.sql`. Prints the recovery-opportunity machine IDs at the end. No pip dependencies — stdlib only.

**Open the frontend:**
```
open frontend/index.html
```
No build step or server needed. Webhook URL is configured in `frontend/config.js`.

**Test the n8n webhook:**
```bash
curl -X POST http://localhost:5678/webhook/coke-on-query \
  -H "Content-Type: application/json" \
  -d '{"query":"Top 10 vending machines by sales?","language":"en"}'
```

## Architecture

```
frontend/config.js        ← webhook URL config (edit this, not index.html)
frontend/index.html       ← single-file SPA; loads config.js before its own <script>
data/generate_data.py     ← generates all 6 CSVs and schema.sql for Supabase
data/schema.sql           ← PostgreSQL DDL; run in Supabase SQL Editor before importing CSVs
n8n/workflow.json         ← importable n8n workflow (Webhook → AI Agent → Respond)
```

### How the pieces connect

1. `frontend/index.html` POSTs `{ query, language }` to `CONFIG.WEBHOOK_URL`
2. n8n Webhook node receives it → AI Agent node processes it
3. AI Agent calls Supabase MCP (local SSE endpoint at `http://localhost:3000/sse`) with `execute_sql` tool
4. Agent returns answer → Respond to Webhook node sends `{ "answer": "..." }`

### Why there are 6 tables

Supabase supports SQL JOINs and aggregations, so cross-table queries are fully supported. The pre-computed tables are kept for query performance and simplicity:

| Table | Type | Purpose |
|---|---|---|
| `users`, `sales`, `app_interactions` | Raw event data | Historical facts |
| `machines` | Context data | Footfall/area type per machine — enables recovery-potential queries |
| `user_metrics` | Pre-computed per user | ChurnRiskScore/Tier — faster churn queries; could also be a SQL view |
| `campaign_segment_performance` | Pre-aggregated | Engagement by age × gender × quarter — faster campaign queries; could also be a SQL view |

When the raw data changes, re-run `generate_data.py` and re-import the CSVs to Supabase.

### Data design decisions

- **Seasonal SKU weighting**: `sales` encodes realistic seasonal demand (Water peaks Jun–Aug, Georgia Coffee peaks Dec–Feb) via `SEASONAL_MULTIPLIERS` in `generate_data.py`. This gives the LLM real patterns to extrapolate from for prediction queries.
- **Recovery-opportunity machines**: 6 machines are deliberately given high `footfall_index` but suppressed sales volume. The script prints their IDs on completion.
- **ChurnRiskScore formula**: `0.6 × normalised(days_since_last_purchase) + 0.4 × purchaseDropRatio` — see `generate_user_metrics()`.

### n8n workflow

The workflow JSON ships with an OpenAI/GPT-4o LLM sub-node. To swap providers: delete the "OpenAI Chat Model" sub-node, add your provider's LLM node, reconnect to the agent's `ai_languageModel` input. The system prompt (in the AI Agent node's `systemMessage` parameter) contains the full 6-table schema and SQL reasoning instructions — edit it there, not in a separate file.

The Supabase MCP sub-node connects to a locally running MCP server (`npx @supabase/mcp-server-supabase@latest --port 3000`) that authenticates to your cloud Supabase project. No credentials are stored in n8n — auth is handled by the MCP server process.

### Frontend

`index.html` is entirely self-contained except for `config.js`. Language switching (`setLang()`) updates all `data-i18n` attributes and re-renders suggestion chips. Markdown tables in responses are parsed and rendered to `<table>` elements by `renderMarkdown()`.
