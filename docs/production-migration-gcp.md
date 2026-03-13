# Production Migration Plan: GCP + Cloud SQL (MySQL/InnoDB)

## Context

The current POC runs on: Supabase (cloud PostgreSQL) + n8n (hosted) + a static HTML frontend with synthetic data.

Moving to production on GCP means connecting to a **pre-existing Cloud SQL (MySQL) database** that already contains real Coke ON transaction data and user PII. We do not know the production schema. Our synthetic schema (`data/schema.sql`), sample CSVs, and data generator (`data/generate_data.py`) are **not relevant** to this migration and will be deleted.

The work is therefore: discover the real schema, adapt the prototype to that schema, and harden the infrastructure for production.

---

## Phase 0: Schema Discovery (do this first — nothing else can proceed without it)

Before changing any code or n8n configuration, obtain and document the production database schema.

### 0a. Get Read-Only Access

Request a read-only MySQL credential from the DBA team:
- `SELECT` privilege only on the relevant database(s)
- No `INSERT`, `UPDATE`, `DELETE`, `DROP`, or `ALTER` rights
- Connect via **Cloud SQL Auth Proxy** or a VPN-controlled bastion — never via public IP

### 0b. Introspect the Schema

Run these queries against the production database:

```sql
-- List all tables
SHOW TABLES;

-- Full column inventory
SELECT
  TABLE_NAME,
  COLUMN_NAME,
  DATA_TYPE,
  CHARACTER_MAXIMUM_LENGTH,
  IS_NULLABLE,
  COLUMN_KEY
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = '<production_db_name>'
ORDER BY TABLE_NAME, ORDINAL_POSITION;

-- Approximate row counts (fast, uses statistics)
SELECT TABLE_NAME, TABLE_ROWS
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = '<production_db_name>'
ORDER BY TABLE_ROWS DESC;

-- Foreign key relationships
SELECT
  TABLE_NAME, COLUMN_NAME,
  REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME
FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
WHERE TABLE_SCHEMA = '<production_db_name>'
  AND REFERENCED_TABLE_NAME IS NOT NULL;
```

### 0c. Map to Analytics Concepts

Identify which production tables correspond to the concepts the POC is built around:

| Analytics concept | POC synthetic table | Production table name (TBD) |
|---|---|---|
| Purchase / transaction records | `sales` | ? |
| User / member records | `users` | ? |
| Vending machine inventory | `machines` | ? |
| App event / engagement logs | `app_interactions` | ? |
| Pre-aggregated reports | `user_metrics`, `campaign_segment_performance` | ? (may not exist) |

If a concept has no production equivalent, that feature must be **removed from the system prompt** — do not ask the LLM to query tables that don't exist.

### 0d. Identify PII Fields

Flag any column that contains personal information:
- Name, email, phone number, address, date of birth
- Any `user_id` that is linkable to an external identity (not just an opaque hash)
- Device identifiers, IP addresses

PII fields must be **excluded from the AI agent's system prompt** — the agent should not be able to select them.

### 0e. Output

Produce a `docs/production-schema.md` that captures table names, column names, data types, row counts, and the analytics concept mapping. **Do not commit this file to the repository if it contains sensitive column names — store it separately or redact before committing.**

---

## Phase 1: Adapt the n8n AI Agent System Prompt

The AI Agent's `systemMessage` (inside `n8n/workflow.json`) currently describes the 6 synthetic tables in detail. This must be completely replaced with the real schema.

### What to change

1. **Replace the Database Schema section** with the real table and column names from Phase 0. Include natural-language descriptions of each column — the LLM needs context, not just names.

2. **Remove concepts with no production equivalent.** If there is no footfall metric, no `footfall_index` column, no campaign engagement table — remove those query patterns entirely. The LLM will hallucinate if the system prompt references tables or columns that don't exist.

3. **Update the SQL dialect** from PostgreSQL to MySQL:

   | What to change | PostgreSQL (current) | MySQL (production) |
   |---|---|---|
   | Case-insensitive LIKE | `ILIKE '%text%'` | `LIKE '%text%'` (utf8mb4_unicode_ci is CI by default) |
   | String concat | `col1 \|\| col2` | `CONCAT(col1, col2)` |
   | Today's date | `CURRENT_DATE` | `CURDATE()` |
   | Date arithmetic | `date - INTERVAL '30 days'` | `DATE_SUB(date, INTERVAL 30 DAY)` |
   | Extract month | `EXTRACT(MONTH FROM date)` | `MONTH(date)` |
   | Format date | `TO_CHAR(date, 'YYYY-MM')` | `DATE_FORMAT(date, '%Y-%m')` |
   | Type cast | `value::NUMERIC` | `CAST(value AS DECIMAL)` |

4. **Replace tool reference:** change `execute_sql` (Supabase MCP) to `execute_query` (MySQL node), or whatever name the replacement tool exposes.

5. **Remove the ×10 sales scaling instruction.** The "multiply sales counts by 10" instruction in the current system prompt is an artefact of the synthetic dataset being a 10% sample. Real data needs no scaling.

6. **Update example SQL patterns** to use real table/column names and MySQL syntax.

---

## Phase 2: Replace the n8n Database Connector

The **Supabase MCP Client** node (`mcp.supabase.com`) is Supabase-specific and must be replaced.

### Recommended: n8n MySQL Tool Node

1. In n8n, add a **MySQL node** configured as an **AI tool** attached to the Agent
2. Configure the credential to point at Cloud SQL via Auth Proxy (`localhost:3306` on the n8n host) or via VPC private IP
3. Store the DB password in the **n8n credential manager** — never in the workflow JSON
4. Attach the MySQL node as a tool on the AI Agent (replacing the Supabase MCP node)
5. Confirm the tool name the agent sees matches what the system prompt references
6. Test with `SHOW TABLES` before running any agent queries

### Alternative: Cloud Run wrapper

If query-level audit logging is a compliance requirement, wrap Cloud SQL behind a lightweight Cloud Run service that logs every query before executing it. Use n8n's HTTP Request node as the tool instead.

### n8n Hosting

For production, move n8n off `n8n.volcanobase.co` to:
- **Cloud Run** (containerised n8n, stateless, scales to zero) — recommended
- Connect to Cloud SQL via Cloud SQL Auth Proxy sidecar
- Store all secrets (OpenAI key, DB password) in **Google Secret Manager**, injected as env vars at runtime

---

## Phase 3: PII & Access Control

Do this before any query runs against real user data.

- **Read-only DB user:** `GRANT SELECT ON <db>.* TO 'analytics_agent'@'%'` — no write or DDL access, ever
- **Exclude PII columns from the system prompt:** if a table has `email`, `full_name`, or `phone_number`, do not list those columns in the agent's schema description — it cannot SELECT what it doesn't know exists
- **Pseudonymous user IDs:** if `user_id` is linkable to a real identity (not an opaque hash), treat it as PII — consider whether the agent should ever return raw user IDs in responses
- **Query audit logging:** log all SQL executed by the agent (query text + timestamp + session ID) to Cloud Logging. This is required for APPI compliance
- **LLM data handling:** OpenAI receives query results as context. Review OpenAI's data retention policy. If retaining data within GCP is required, switch to Vertex AI (Gemini) — this keeps all data under Google's BAA and within the `asia-northeast1` region

---

## Phase 4: GCP Infrastructure

| Component | Service | Notes |
|---|---|---|
| Database | Cloud SQL (MySQL 8.0, pre-existing) | Private IP only, asia-northeast1 |
| DB Proxy | Cloud SQL Auth Proxy | Sidecar on Cloud Run or VM |
| Frontend hosting | Firebase Hosting or Cloud Storage + Cloud CDN | Static assets, global CDN |
| n8n orchestration | Cloud Run (containerised n8n) | Stateless, auto-scales to zero |
| Secrets | Secret Manager | All API keys, DB credentials |
| Networking | VPC + Private Service Connect | DB not exposed to internet |
| WAF / Rate limiting | Cloud Armor | Webhook endpoint protection |
| LLM API | OpenAI (unchanged) or Vertex AI (Gemini) | Vertex avoids external egress, preferred for PII |
| Monitoring | Cloud Logging + Cloud Monitoring | Dashboards for latency, errors, LLM cost |

---

## Phase 5: Authentication & Security Hardening

The webhook is currently open (no auth, CORS `*`). For production:

- **Webhook auth:** Add API key header check in n8n — reject requests missing `X-API-Key`
- **CORS:** Restrict to the production frontend origin only
- **Rate limiting:** Cloud Armor rule — e.g. 60 requests/minute per IP
- **SQL injection:** n8n MySQL node uses parameterised queries; the agent constructs SQL from user intent rather than interpolating raw strings — document this constraint explicitly

---

## Phase 6: Frontend Updates

### Suggested questions
`frontend/index.html` lines 384–423 contain hardcoded suggested questions referencing our synthetic data concepts (Georgia Coffee, footfall, churn tiers, campaign IDs). After schema discovery, update these to reference:
- Real product/SKU names from the production DB
- Real analytics capabilities based on what tables and columns actually exist
- Remove any concept that has no production equivalent

### Webhook URL
`frontend/assets/js/config.js` hardcodes the webhook URL. Replace with an environment-injected value at deploy time (CI variable or separate `config.prod.js`). Enable HTTPS (Firebase Hosting provides SSL automatically). Add `Content-Security-Policy` headers.

---

## Phase 7: Monitoring & Observability

| Signal | Tool | Alert Threshold |
|---|---|---|
| Webhook error rate | Cloud Monitoring | >5% 5xx over 5 min |
| p95 query latency | Cloud Monitoring | >3s |
| LLM token spend | OpenAI usage API (polled via n8n CRON) | >$X/day |
| DB CPU/disk | Cloud SQL metrics | >80% CPU |
| n8n execution failures | n8n built-in + Cloud Logging | Any consecutive failure |

---

## APPI Compliance (Japan)

When real Coke ON user data is involved:

- **Data residency:** All data must remain in `asia-northeast1` — confirm Cloud SQL, Cloud Run, and CDN edge caching comply
- **Retention limits:** Define and enforce retention periods for raw transaction data and logs
- **Right to erasure:** Implement a process to delete a user's records on request
- **Anonymisation:** Consider whether analytics can be served from aggregated data only, avoiding raw user records entirely
- **Processing agreements:** Confirm DPA coverage between Coca-Cola, the n8n operator, and OpenAI (or Vertex AI)

---

## Files Requiring Changes

| File | Change |
|---|---|
| AI Agent `systemMessage` in `n8n/workflow.json` | Full rewrite: real table/column names, MySQL dialect, remove scaling factor, remove non-existent concepts |
| `n8n/workflow.json` | Replace Supabase MCP node with MySQL Tool node; update credential references |
| `frontend/index.html` | Update suggested questions to match real schema concepts and real product names |
| `frontend/assets/js/config.js` | Replace hardcoded webhook URL with environment-injected value |
| `SETUP.md` | Full rewrite: GCP setup steps |
| New: `docs/production-schema.md` | Schema discovery output — mapping of real tables to analytics concepts (store separately if sensitive) |
| New: `infra/` | Terraform or gcloud CLI scripts for Cloud SQL connection, Cloud Run n8n, Firebase, Secret Manager |

## Files to Delete (not rewrite)

| File | Reason |
|---|---|
| `data/schema.sql` | Describes our synthetic schema — irrelevant to production DB |
| `data/generate_data.py` | Generates synthetic data — irrelevant; production data already exists |
| `data/*.csv` | Synthetic data files |

---

## Key Risks

| Risk | Mitigation |
|---|---|
| Production schema is far more complex than our 6-table design | Start with 3–4 core tables; expand system prompt incrementally; test each capability before adding the next |
| PII exposure through ad-hoc LLM-generated SQL | Read-only DB user + exclude PII columns from system prompt + audit logging |
| Analytics concepts from POC have no production equivalent | Schema discovery (Phase 0) gates everything else — remove unsupported features cleanly |
| Real data volumes cause slow or expensive queries | Add query guardrails to system prompt: always use LIMIT, avoid full-table scans, require WHERE clauses on date columns |
| LLM hallucinates column/table names | System prompt must be precise; test with adversarial queries that reference non-existent columns |
