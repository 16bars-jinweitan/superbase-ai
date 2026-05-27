# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Coke ON Analytics POC — a bilingual (EN/JA) natural language analytics interface. See `docs/coke-on-poc-scope.md` for full requirements and `docs/SETUP.md` for wiring instructions.

## Commands

**Regenerate all CSV data and schema:**
```bash
cd data && python3 generate_data.py
```
No pip dependencies — stdlib only.

**Open the frontend:**
```
open frontend/index.html
ruby -run -e httpd frontend -p 5500 -b 127.0.0.1
```
No build step. Webhook URL is configured in `frontend/assets/js/config.js` — edit that file, not `index.html`.

## Architecture

### Why there are 6 tables

Three raw-event tables (`users`, `sales`, `app_interactions`) plus `machines` for footfall context. The other two (`user_metrics`, `campaign_segment_performance`) are pre-computed for query performance — they could instead be SQL views. When the raw data changes, re-run `generate_data.py` and re-import the CSVs to Supabase.

### Data design decisions

- **Seasonal SKU weighting**: `sales` encodes realistic seasonal demand via `SEASONAL_MULTIPLIERS` in `generate_data.py`. This gives the LLM real patterns to extrapolate from for prediction queries.
- **Recovery-opportunity machines**: 6 machines are deliberately given high `footfall_index` but suppressed sales volume — designed for LLM recovery-potential queries.
- **Dataset temporal coverage**: data spans 2024-Q4 through 2026-Q1. The system prompt tells the LLM to use this the last 3 months as range when resolving ambiguous references.

### Volume scaling (critical)

The database holds a compact sample (500 users, ~20K sales, ~3K interactions). The system prompt instructs the LLM to silently multiply figures before presenting them (sales ×50, users ×200, interactions ×200). Rates, averages, and machine counts are not scaled. If you change the sample size in `generate_data.py`, you must also update the scaling multipliers in the system prompt inside `n8n/workflow.json`.

### n8n workflow

**System prompt**: the authoritative copy lives in the AI Agent node's `systemMessage` parameter inside `n8n/workflow.json`. The file `n8n/system-prompt.md` is a human-readable reference copy — it is **not** loaded by n8n. When editing the system prompt, update `workflow.json` (the source of truth) and optionally sync `system-prompt.md` for readability.

**Supabase MCP**: the workflow uses the hosted Supabase MCP endpoint (`https://mcp.supabase.com/mcp?project_ref=...`), authenticated via a Header Auth credential containing a Supabase PAT stored in n8n's credential manager. No local MCP server is needed.

**Stateless sessions**: the Simple Memory node keys on `$execution.id`, so each webhook request is independent — there is no conversation continuity between requests.

**Webhook contract**: the frontend POSTs `{ query, language }` and expects `{ answer: "..." }` back. The response body is raw HTML (three `ai-card` divs) rendered directly via `innerHTML`.

### Voice mode

An ElevenLabs Conversational AI widget is embedded in `index.html`. The webhook node detects `ElevenLabs` in the User-Agent header and auto-prepends `[VOICE]` to the query. When the system prompt sees the `[VOICE]` prefix, it responds with plain text instead of HTML cards so the response can be read aloud.

### Frontend auth

A simple client-side password gate protects the demo. The password is stored in `frontend/assets/js/config.js` and checked via `sessionStorage` — it is not a security boundary.
