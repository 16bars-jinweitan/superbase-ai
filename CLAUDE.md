# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Coke ON Analytics POC — a bilingual (EN/JA) natural language analytics interface. See `coke-on-poc-scope.md` for full requirements and `SETUP.md` for wiring instructions.

## Commands

**Regenerate all CSV data and schema:**
```bash
cd data && python3 generate_data.py
```
No pip dependencies — stdlib only.

**Open the frontend:**
```
open frontend/index.html
```
No build step. Webhook URL is configured in `frontend/config.js` — edit that file, not `index.html`.

## Architecture

### Why there are 6 tables

Three raw-event tables (`users`, `sales`, `app_interactions`) plus `machines` for footfall context. The other two (`user_metrics`, `campaign_segment_performance`) are pre-computed for query performance — they could instead be SQL views. When the raw data changes, re-run `generate_data.py` and re-import the CSVs to Supabase.

### Data design decisions

- **Seasonal SKU weighting**: `sales` encodes realistic seasonal demand via `SEASONAL_MULTIPLIERS` in `generate_data.py`. This gives the LLM real patterns to extrapolate from for prediction queries.
- **Recovery-opportunity machines**: 6 machines are deliberately given high `footfall_index` but suppressed sales volume — designed for LLM recovery-potential queries.

### n8n workflow

The system prompt containing the full schema and SQL reasoning instructions lives in the AI Agent node's `systemMessage` parameter — edit it there, not in a separate file.

The `localhost:3000/sse` MCP endpoint is a locally running server that authenticates to the cloud Supabase project. No credentials are stored in n8n.
