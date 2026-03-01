# Setup Guide

## 1. Generate data and schema

```bash
cd data && python3 generate_data.py
```

This writes 6 CSV files and `data/schema.sql`.

## 2. Create tables in Supabase

Supabase is cloud-hosted — no local install needed.

1. Go to your Supabase project dashboard → **SQL Editor**
2. Paste the contents of `data/schema.sql` and click **Run** (creates all 6 tables)
3. For each table, go to **Table Editor** → select the table → **Import data from CSV** and upload the corresponding file:

| Table | CSV file |
|---|---|
| `users` | `data/users.csv` |
| `sales` | `data/sales.csv` |
| `machines` | `data/machines.csv` |
| `app_interactions` | `data/app_interactions.csv` |
| `user_metrics` | `data/user_metrics.csv` |
| `campaign_segment_performance` | `data/campaign_segment_performance.csv` |

4. Data is now in Supabase. No credentials needed here — the MCP connection is configured in n8n in step 4.

## 3. Import workflow into n8n

Go to **n8n → Workflows → Import from file** and select `n8n/workflow.json`.

## 4. Wire credentials in n8n

**LLM sub-node** — The workflow defaults to OpenAI / GPT-4o. To swap providers, delete the "OpenAI Chat Model" sub-node and add your preferred LLM node, then reconnect it to the agent's `ai_languageModel` input.

**Supabase MCP sub-node** — The Supabase MCP is configured as a tool node connected to the AI Agent node inside n8n. Credentials are stored in n8n's credential manager — no separate process needs to be started.

In n8n, create a **Header Auth** credential containing your Supabase personal access token (get it from [supabase.com/dashboard/account/tokens](https://supabase.com/dashboard/account/tokens)), then assign it to the **Supabase MCP** tool node. The node connects to `https://mcp.supabase.com/sse`.

## 5. Configure the frontend

If n8n runs on a port other than **5678**, update `frontend/config.js`:

```js
const CONFIG = {
  WEBHOOK_URL: "http://localhost:5678/webhook/coke-on-query",
};
```

## 6. Test end-to-end

Open `frontend/index.html` directly in a browser (no server needed).

Or test the webhook directly:

```bash
# English
curl -X POST http://localhost:5678/webhook/coke-on-query \
  -H "Content-Type: application/json" \
  -d '{"query":"Which are the top 10 vending machines by sales?","language":"en"}'

# Japanese
curl -X POST http://localhost:5678/webhook/coke-on-query \
  -H "Content-Type: application/json" \
  -d '{"query":"販売数トップ10の自動販売機はどれですか？","language":"ja"}'
```

Expected response shape: `{ "answer": "..." }`

## Re-generating data

```bash
cd data
python3 generate_data.py
```

Outputs all 6 CSV files and `schema.sql`. Re-run the schema SQL and re-import the CSVs to Supabase if the data changes. The script also prints which machines are designated as recovery-opportunity machines (high footfall, low sales).
