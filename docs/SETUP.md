# Setup Guide

## 1. Generate data and schema

```bash
cd data && python3 generate_data.py
```

This writes 6 CSV files and `data/schema.sql`. Key data design choices:

- **Sales**: timestamps (date + time of day), day-of-week weighting, `unit_price` per SKU
- **Purchase frequency**: each user is assigned a `purchase_rate_weight` at generation time, producing a realistic spread across four segments — `Daily+` (≤2 day avg gap), `Weekly+` (≤7 days), `Monthly` (≤30 days), `Monthly-` (>30 days). The segment is pre-computed and stored in `user_metrics.frequency_segment`.
- **SKU loyalty**: ~35% of users are "loyal" (one SKU gets 6× the probability of others); the remaining 65% explore freely. Preference multipliers are combined with seasonal weights, so a loyal Georgia Coffee drinker still buys slightly less of it in summer.
- **Temporal integrity**: every sale is guaranteed to occur on or after the purchasing user's `join_date`.

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

In n8n, create a **Header Auth** credential containing your Supabase personal access token (get it from [supabase.com/dashboard/account/tokens](https://supabase.com/dashboard/account/tokens)), then assign it to the **Supabase MCP** tool node. The node connects to:
```
https://mcp.supabase.com/mcp?project_ref=<your-project-ref>&read_only=true&features=database
```

## 5. Configure the frontend

The webhook URL is already set in `frontend/config.js`. No changes needed unless you redeploy n8n to a different host.

```js
const CONFIG = {
  WEBHOOK_URL: "https://n8n.volcanobase.co/webhook/coke-on-query",
};
```

## 6. Test end-to-end

Open `frontend/index.html` directly in a browser (no server needed).

Or test the webhook directly (use the test URL while the workflow is open in n8n, production URL otherwise):

```bash
# English (production)
curl -X POST https://n8n.volcanobase.co/webhook/coke-on-query \
  -H "Content-Type: application/json" \
  -d '{"query":"Which are the top 10 vending machines by sales?","language":"en"}'

# English (test — workflow must be open in n8n)
curl -X POST https://n8n.volcanobase.co/webhook-test/coke-on-query \
  -H "Content-Type: application/json" \
  -d '{"query":"Which are the top 10 vending machines by sales?","language":"en"}'

# Japanese
curl -X POST https://n8n.volcanobase.co/webhook/coke-on-query \
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

## Volume scaling

The database holds a compact sample (500 users, 20K sales, 3K interactions). The system prompt instructs the LLM to silently scale figures before presenting them so they appear realistic:

| Metric | DB rows | Presented as | Multiplier |
|---|---|---|---|
| Sales counts / revenue | 20,000 | ~1,000,000 | ×50 |
| User counts | 500 | ~100,000 | ×200 |
| App interactions | 3,000 | ~600,000 | ×200 |
| Campaign engagement / unique users | raw values | scaled | ×200 |

Rates, percentages, per-user metrics, averages, and machine counts are **not** scaled. The scaling rules live in the `## Volume Scaling` section of the AI Agent system prompt in `n8n/workflow.json`.
