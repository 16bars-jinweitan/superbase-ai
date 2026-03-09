# Production Migration Plan: GCP + Cloud SQL (MySQL/InnoDB)

## Context

The current POC runs on: Supabase (cloud PostgreSQL) + n8n (hosted) + a static HTML frontend. Moving to GCP with Cloud SQL (MySQL 8.0 / InnoDB) is the most significant change — it triggers a cascade of updates across the schema, the n8n AI Agent's SQL dialect, the database connector, infrastructure, and compliance posture. This document covers every layer.

---

## 1. Database: PostgreSQL → MySQL/InnoDB on Cloud SQL

### 1a. Cloud SQL Instance Setup
- Engine: **MySQL 8.0** (InnoDB default, full window function support, utf8mb4 charset)
- Region: `asia-northeast1` (Tokyo) — required for data residency with Japanese user PII
- Tier: `db-n1-standard-2` or `db-g1-small` for early production; scale via Cloud SQL's vertical autoscaling
- Enable **Private IP** only (no public IP); connect via Cloud SQL Auth Proxy or VPC peering
- Enable **automated backups** (daily, 7-day retention minimum) and PITR

### 1b. Schema Translation (PostgreSQL → MySQL)

Key differences to address in `data/schema.sql`:

| PostgreSQL | MySQL equivalent | Notes |
|---|---|---|
| `TEXT PRIMARY KEY` | `VARCHAR(20) PRIMARY KEY` | Size text PKs explicitly |
| `NUMERIC` | `DECIMAL(10,4)` | Explicit precision |
| `DATE` | `DATE` | Same |
| `INTEGER` | `INT` | Same |
| `ILIKE` in queries | `LIKE` (or `REGEXP`) | Case-insensitive by default in MySQL utf8mb4 |
| `\|\|` string concat | `CONCAT()` | Different operator |
| `CURRENT_DATE` | `CURDATE()` | MySQL equivalent |
| No FK constraints | Explicit `FOREIGN KEY` + `REFERENCES` | InnoDB enforces these |

Add `CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci` to all tables for full Japanese text support.

### 1c. Indexes to Add (missing in current schema)

```sql
-- sales: core analytical join & filter paths
CREATE INDEX idx_sales_user_id       ON sales(user_id);
CREATE INDEX idx_sales_purchase_date ON sales(purchase_date);
CREATE INDEX idx_sales_machine_id    ON sales(machine_id);
CREATE INDEX idx_sales_sku           ON sales(sku);

-- app_interactions
CREATE INDEX idx_ai_user_id          ON app_interactions(user_id);
CREATE INDEX idx_ai_event_date       ON app_interactions(event_date);
CREATE INDEX idx_ai_event_type       ON app_interactions(event_type);

-- user_metrics: churn queries
CREATE INDEX idx_um_churn_tier       ON user_metrics(churn_risk_tier);
CREATE INDEX idx_um_churn_score      ON user_metrics(churn_risk_score);
```

### 1d. Foreign Key Constraints to Add
Currently absent from the schema — add to enforce referential integrity:
```sql
ALTER TABLE sales            ADD CONSTRAINT fk_sales_user     FOREIGN KEY (user_id)    REFERENCES users(user_id);
ALTER TABLE sales            ADD CONSTRAINT fk_sales_machine  FOREIGN KEY (machine_id) REFERENCES machines(machine_id);
ALTER TABLE app_interactions ADD CONSTRAINT fk_ai_user        FOREIGN KEY (user_id)    REFERENCES users(user_id);
ALTER TABLE user_metrics     ADD CONSTRAINT fk_um_user        FOREIGN KEY (user_id)    REFERENCES users(user_id);
```

### 1e. Data Migration
- Export Supabase tables as CSV (current process already produces these)
- Import via `LOAD DATA INFILE` or Cloud SQL import from Cloud Storage bucket
- Validate row counts and spot-check seasonal patterns post-import

---

## 2. n8n: Replace Supabase MCP with Cloud SQL Connector

The **Supabase MCP Client** node (`mcp.supabase.com`) must be replaced — it is Supabase-specific. Two options:

### Option A (Recommended): n8n MySQL Tool Node
- Use n8n's native `MySQL` node configured as an **AI tool** attached to the Agent
- Credential: Cloud SQL Auth Proxy (localhost:3306) or Cloud SQL connector via VPC
- Store connection string in **n8n credential manager** (not in workflow JSON)
- The agent uses `execute_query` action instead of Supabase's `execute_sql`

### Option B: Custom HTTP Tool → Cloud SQL REST API
- Use n8n HTTP Request node as a tool, calling a lightweight Cloud Run wrapper that executes parameterized SQL
- More boilerplate but allows fine-grained query auditing and logging
- Recommended if query-level access logging is a compliance requirement

### n8n Deployment Change
- Current n8n is at `n8n.volcanobase.co` (unknown hosting)
- For GCP production: deploy n8n on **Cloud Run** (containerized) or **GKE**
- Connect to Cloud SQL via **Cloud SQL Auth Proxy** sidecar
- Store all secrets (OpenAI key, DB password) in **Google Secret Manager**, injected as env vars

---

## 3. AI Agent System Prompt: SQL Dialect Update

The system prompt inside the AI Agent node contains PostgreSQL-flavoured SQL reasoning instructions. For MySQL these must change:

| What to change | From | To |
|---|---|---|
| Case-insensitive LIKE | `ILIKE '%text%'` | `LIKE '%text%'` (utf8mb4 is CI by default) |
| String concat | `col1 \|\| col2` | `CONCAT(col1, col2)` |
| Today's date | `CURRENT_DATE` | `CURDATE()` |
| Date diff | `purchase_date - INTERVAL '30 days'` | `DATE_SUB(CURDATE(), INTERVAL 30 DAY)` |
| Extract month | `EXTRACT(MONTH FROM date)` | `MONTH(date)` |
| Type cast | `value::NUMERIC` | `CAST(value AS DECIMAL)` |
| Null-safe | `COALESCE` | `COALESCE` (same) |
| Limit | `LIMIT n` | `LIMIT n` (same) |

The tool reference in the prompt must also change from `execute_sql` (Supabase MCP) to `execute_query` (MySQL node) or whatever the new tool exposes.

---

## 4. GCP Infrastructure

| Component | Service | Notes |
|---|---|---|
| Database | Cloud SQL (MySQL 8.0) | Private IP, asia-northeast1 |
| DB Proxy | Cloud SQL Auth Proxy | Sidecar on Cloud Run or VM |
| Frontend hosting | Firebase Hosting or Cloud Storage + Cloud CDN | Static assets, global CDN |
| n8n orchestration | Cloud Run (containerised n8n) | Stateless, auto-scales to zero |
| Secrets | Secret Manager | All API keys, DB credentials |
| Networking | VPC + Private Service Connect | DB not exposed to internet |
| WAF / Rate limiting | Cloud Armor | Webhook endpoint protection |
| LLM API | OpenAI (unchanged) or Vertex AI (Gemini) | Vertex avoids external egress |
| Monitoring | Cloud Logging + Cloud Monitoring | Dashboards for latency, errors, LLM cost |

---

## 5. Authentication & Security Hardening

Currently the webhook is **completely open** (no auth, CORS `*`). For production:

- **Webhook auth:** Add API key header check in n8n (or Cloud Armor header rule) — reject requests missing `X-API-Key`
- **CORS:** Restrict to the production frontend origin (e.g. `https://coke-on.example.com`)
- **Rate limiting:** Cloud Armor rule — e.g. 60 requests/minute per IP
- **Read-only DB user:** Create a MySQL user with only `SELECT` privilege — removes any risk of LLM-prompted writes even if the system prompt is bypassed
- **SQL injection:** n8n MySQL node uses parameterized queries; the agent constructs queries from intent rather than interpolating raw user strings — this design is acceptable, but should be documented as a constraint
- **Frontend config:** Move `CONFIG.WEBHOOK_URL` to a build-time env var or CI secret; never hardcode production URLs in source

---

## 6. Data Pipeline: Table Refresh

`user_metrics` and `campaign_segment_performance` are currently generated as static CSVs. In production with live data:

- **Option A (Simplest):** Scheduled n8n workflow (nightly CRON) that rebuilds the two pre-computed tables via SQL `INSERT … SELECT` against the raw tables
- **Option B:** Replace both tables with **MySQL views** — eliminates staleness entirely, slight query-time cost (acceptable at current data scale)
- **Option C (Future):** Cloud Composer (Airflow) DAG for complex ETL as data grows

Recommended for production launch: **Option A** — nightly rebuild via n8n CRON. Migrate to views if query latency becomes an issue.

---

## 7. Frontend Hosting

- Move from file-based to **Firebase Hosting** (simplest for static SPA) or Cloud Storage bucket + Cloud CDN
- `frontend/assets/js/config.js` → replace `WEBHOOK_URL` hardcode with a value injected at deploy time (CI variable or separate `config.prod.js`)
- Enable HTTPS (Firebase Hosting provides SSL automatically)
- Add `Content-Security-Policy` header to restrict script sources

---

## 8. Compliance & Data Governance

When real Coke ON user data replaces synthetic data:

- **APPI compliance** (Japan's Personal Information Protection Act): user_id, age, gender, region are personal data — requires data processing agreements, retention limits, and right-to-erasure implementation
- **Data residency:** All data must remain in `asia-northeast1`; confirm Cloud SQL, Cloud Run, and Cloud CDN edge caching comply
- **Anonymisation:** Consider hashing `user_id` and bucketing `age` into groups before storing if raw PII is not needed for analytics
- **Audit logging:** Enable Cloud SQL audit logging; log all `execute_query` calls from the AI agent (query text, timestamp, user session)
- **LLM data handling:** Review OpenAI's data retention policy for API inputs; consider Vertex AI (Gemini) to keep data within GCP and under Google's BAA

---

## 9. Monitoring & Observability

| Signal | Tool | Alert Threshold |
|---|---|---|
| Webhook error rate | Cloud Monitoring | >5% 5xx over 5 min |
| p95 query latency | Cloud Monitoring | >3s |
| LLM token spend | OpenAI usage API (polled via n8n CRON) | >$X/day |
| DB CPU/disk | Cloud SQL metrics | >80% CPU |
| n8n execution failures | n8n built-in + Cloud Logging | Any consecutive failure |

---

## 10. Summary of Files Requiring Changes

| File | Change Required |
|---|---|
| `data/schema.sql` | Full rewrite: MySQL DDL, utf8mb4 charset, FK constraints, indexes |
| `data/generate_data.py` | Minor: update schema.sql output to MySQL syntax |
| `n8n/workflow.json` | Replace Supabase MCP node with MySQL Tool node; update credential references |
| AI Agent `systemMessage` | SQL dialect changes (see Section 3); update tool name |
| `frontend/assets/js/config.js` | Replace hardcoded URL with environment-injected value |
| `SETUP.md` | Full rewrite: GCP setup steps instead of Supabase/n8n.volcanobase instructions |
| New: `infra/` directory | Terraform or gcloud CLI scripts for Cloud SQL, Cloud Run, Firebase, Secret Manager |
| New: `sql/refresh_computed_tables.sql` | Nightly rebuild queries for `user_metrics` and `campaign_segment_performance` |
