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

4. Copy your **Project URL** (`https://<ref>.supabase.co`) and **service_role key** from **Project Settings → API**.

## 3. Import workflow into n8n

Go to **n8n → Workflows → Import from file** and select `n8n/workflow.json`.

## 4. Wire credentials in n8n

**LLM sub-node** — The workflow defaults to OpenAI / GPT-4o. To swap providers, delete the "OpenAI Chat Model" sub-node and add your preferred LLM node, then reconnect it to the agent's `ai_languageModel` input.

**Supabase MCP sub-node** — The MCP server runs locally on your machine and connects to your cloud Supabase project. Start it before running the n8n workflow:

```bash
SUPABASE_URL=https://<ref>.supabase.co \
SUPABASE_KEY=<your-service_role-key> \
npx @supabase/mcp-server-supabase@latest --port 3000
```

The SSE endpoint is pre-configured in the workflow as `http://localhost:3000/sse`. No credential entry is needed in n8n — authentication is handled by the MCP server process.

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
