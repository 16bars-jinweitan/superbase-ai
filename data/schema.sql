-- Coke ON Analytics POC — PostgreSQL schema for Supabase
-- Run this in the Supabase SQL Editor before importing CSVs.
-- Drops and recreates all tables — safe for POC (synthetic data only).

DROP TABLE IF EXISTS campaign_segment_performance, user_metrics, app_interactions, sales, machines, users CASCADE;

CREATE TABLE users (
    user_id          TEXT PRIMARY KEY,
    join_date        DATE NOT NULL,
    age              INTEGER NOT NULL,
    gender           TEXT NOT NULL,
    region           TEXT NOT NULL,
    sku_loyalty_type TEXT NOT NULL,
    preferred_sku    TEXT NOT NULL
);

CREATE TABLE machines (
    machine_id     TEXT PRIMARY KEY,
    location       TEXT NOT NULL,
    area_type      TEXT NOT NULL,
    footfall_tier  TEXT NOT NULL,
    footfall_index INTEGER NOT NULL
);

CREATE TABLE sales (
    sale_id          TEXT PRIMARY KEY,
    user_id          TEXT NOT NULL,
    sku              TEXT NOT NULL,
    purchase_date    TIMESTAMP NOT NULL,
    machine_id       TEXT NOT NULL,
    machine_location TEXT NOT NULL,
    unit_price       INTEGER NOT NULL
);

CREATE TABLE app_interactions (
    interaction_id TEXT PRIMARY KEY,
    user_id        TEXT NOT NULL,
    event_type     TEXT NOT NULL,
    campaign_id    TEXT,
    campaign_name  TEXT,
    event_date     DATE NOT NULL
);

CREATE TABLE user_metrics (
    user_id                    TEXT PRIMARY KEY,
    last_purchase_date         DATE,
    days_since_last_purchase   INTEGER NOT NULL,
    total_purchases            INTEGER NOT NULL,
    purchases_30d              INTEGER NOT NULL,
    purchases_90d              INTEGER NOT NULL,
    avg_days_between_purchases NUMERIC NOT NULL,
    total_revenue              INTEGER NOT NULL,
    churn_risk_score           NUMERIC NOT NULL,
    churn_risk_tier            TEXT NOT NULL,
    frequency_segment          TEXT NOT NULL
);

CREATE TABLE campaign_segment_performance (
    campaign_id      TEXT NOT NULL,
    campaign_name    TEXT NOT NULL,
    age_group        TEXT NOT NULL,
    gender           TEXT NOT NULL,
    quarter          TEXT NOT NULL,
    engagement_count INTEGER NOT NULL,
    unique_users     INTEGER NOT NULL,
    engagement_rate  NUMERIC NOT NULL,
    PRIMARY KEY (campaign_id, age_group, gender, quarter)
);
