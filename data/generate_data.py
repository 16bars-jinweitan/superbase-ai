"""
Synthetic data generator for Coke ON Analytics POC.
Generates six CSV files for Supabase import and schema.sql for table creation:

  Raw event tables:
  - users.csv                       (~500 rows)
  - sales.csv                       (~5,000 rows, with seasonal SKU weighting)
  - app_interactions.csv            (~3,000 rows)

  Pre-computed / context tables (kept for query performance):
  - machines.csv                    (50 rows — footfall context per machine)
  - user_metrics.csv                (500 rows — one per user, churn indicators)
  - campaign_segment_performance.csv (~240 rows — engagement by age/gender/quarter)

  PostgreSQL schema:
  - schema.sql                      (CREATE TABLE statements for all 6 tables)

No external dependencies — stdlib only.
Run: python3 generate_data.py
"""

import csv
import random
import uuid
from collections import defaultdict
from datetime import date, timedelta

random.seed(42)

TODAY = date(2026, 3, 1)

# ─── Reference data ──────────────────────────────────────────────────────────

REGIONS = [
    "Tokyo", "Osaka", "Aichi", "Fukuoka", "Kanagawa",
    "Saitama", "Chiba", "Hokkaido", "Hyogo", "Kyoto",
]
REGION_WEIGHTS = [25, 15, 10, 8, 8, 7, 7, 6, 7, 7]

GENDERS = ["Male", "Female", "Other"]
GENDER_WEIGHTS = [45, 45, 10]

SKUS = ["Georgia Coffee", "Coca-Cola", "Water", "Fanta", "Aquarius"]
BASE_SKU_WEIGHTS = [40, 25, 20, 10, 5]

# Seasonal SKU multipliers by month (1=Jan … 12=Dec)
# Positive seasons for each product:
#   Georgia Coffee: peaks Dec–Feb (winter), dips Jun–Aug
#   Water/Aquarius: peaks Jun–Aug (summer), dips Dec–Feb
#   Fanta:          slight summer peak
SEASONAL_MULTIPLIERS = {
    # month: [Georgia Coffee, Coca-Cola, Water, Fanta, Aquarius]
    1:  [1.50, 1.00, 0.55, 0.75, 0.60],   # Jan  — winter
    2:  [1.50, 1.00, 0.55, 0.75, 0.60],   # Feb  — winter
    3:  [1.15, 1.00, 0.85, 0.90, 0.85],   # Mar  — spring
    4:  [1.00, 1.00, 1.00, 1.00, 1.00],   # Apr  — baseline
    5:  [1.00, 1.05, 1.10, 1.05, 1.10],   # May  — late spring
    6:  [0.65, 1.10, 1.60, 1.30, 1.50],   # Jun  — summer
    7:  [0.60, 1.15, 1.75, 1.40, 1.60],   # Jul  — peak summer
    8:  [0.60, 1.15, 1.75, 1.35, 1.55],   # Aug  — peak summer
    9:  [0.85, 1.05, 1.20, 1.10, 1.15],   # Sep  — early autumn
    10: [1.20, 1.00, 0.85, 0.90, 0.85],   # Oct  — autumn
    11: [1.35, 1.00, 0.65, 0.80, 0.70],   # Nov  — late autumn
    12: [1.50, 1.00, 0.55, 0.75, 0.60],   # Dec  — winter
}

AREA_TYPES = ["Transit Hub", "Office District", "Residential", "Tourist", "University", "Retail"]
AREA_TYPE_WEIGHTS = [20, 25, 20, 15, 10, 10]

FOOTFALL_TIERS = ["High", "Medium", "Low"]

EVENT_TYPES = ["LoggedIn", "EarnedStamp", "EngagedCampaign"]
EVENT_WEIGHTS = [50, 30, 20]

CAMPAIGNS = [
    ("CAMP-001", "Natsu Summer Campaign"),
    ("CAMP-002", "Winter Reward"),
    ("CAMP-003", "Georgia Points Boost"),
    ("CAMP-004", "Spring Fresh Start"),
    ("CAMP-005", "Weekend Double Stamps"),
    ("CAMP-006", "Hydration Challenge"),
    ("CAMP-007", "Morning Commuter Bonus"),
    ("CAMP-008", "Regional Special"),
]

AGE_GROUPS = ["18-24", "25-34", "35-44", "45-54", "55-65"]

# Campaign engagement affinity by age group index (0=18-24 … 4=55-65)
# Higher weight = more likely this age group engages with this campaign
CAMPAIGN_AGE_AFFINITY = {
    "CAMP-001": [2.0, 1.5, 1.0, 0.7, 0.5],   # Summer: skews young
    "CAMP-002": [0.8, 1.0, 1.2, 1.5, 1.8],   # Winter: skews older
    "CAMP-003": [0.7, 0.9, 1.5, 1.8, 1.6],   # Georgia: skews 35+
    "CAMP-004": [1.2, 1.3, 1.1, 0.9, 0.8],   # Spring: younger-ish
    "CAMP-005": [1.5, 1.4, 1.0, 0.8, 0.6],   # Weekends: young/mid
    "CAMP-006": [1.3, 1.5, 1.2, 0.9, 0.7],   # Hydration: 25-34 peak
    "CAMP-007": [0.9, 1.4, 1.5, 1.2, 0.8],   # Commuter: 25-44
    "CAMP-008": [1.0, 1.0, 1.0, 1.0, 1.0],   # Regional: neutral
}

# Campaign engagement affinity by gender index (0=Male, 1=Female, 2=Other)
CAMPAIGN_GENDER_AFFINITY = {
    "CAMP-001": [0.9, 1.3, 1.0],
    "CAMP-002": [1.1, 0.9, 1.0],
    "CAMP-003": [1.4, 0.7, 0.9],
    "CAMP-004": [0.9, 1.2, 1.1],
    "CAMP-005": [1.0, 1.1, 1.0],
    "CAMP-006": [0.7, 1.4, 1.2],
    "CAMP-007": [1.2, 0.9, 1.0],
    "CAMP-008": [1.0, 1.0, 1.0],
}

NUM_MACHINES = 50
MACHINE_IDS = [f"MACH-{str(i).zfill(3)}" for i in range(1, NUM_MACHINES + 1)]


# ─── Helpers ─────────────────────────────────────────────────────────────────

def random_date(start: date, end: date) -> date:
    delta = (end - start).days
    if delta <= 0:
        return start
    return start + timedelta(days=random.randint(0, delta))


def uid() -> str:
    return str(uuid.uuid4())


def weighted_choice(population, weights):
    return random.choices(population, weights=weights, k=1)[0]


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def quarter_label(d: date) -> str:
    q = (d.month - 1) // 3 + 1
    return f"{d.year}-Q{q}"


def age_group(age: int) -> str:
    for group in AGE_GROUPS:
        lo, hi = map(int, group.split("-"))
        if lo <= age <= hi:
            return group
    return "55-65"


# ─── Users ───────────────────────────────────────────────────────────────────

def generate_users(n=500):
    rows = []
    join_start = TODAY - timedelta(days=730)
    for _ in range(n):
        days_ago = int(abs(random.gauss(90, 100)))
        join_date = TODAY - timedelta(days=min(days_ago, 730))
        join_date = max(join_date, join_start)
        age = clamp(int(random.gauss(32, 10)), 18, 65)
        rows.append({
            "user_id": f"USR-{uid()[:8].upper()}",
            "join_date": join_date.isoformat(),
            "age": age,
            "gender": weighted_choice(GENDERS, GENDER_WEIGHTS),
            "region": weighted_choice(REGIONS, REGION_WEIGHTS),
        })
    return rows


# ─── Machines ────────────────────────────────────────────────────────────────

def generate_machines():
    """
    50 machines with footfall context. Some High-footfall machines are
    deliberately placed in low-sales-volume zones to create visible
    'recovery opportunity' signals for the predictive queries.
    """
    rows = []
    # Pre-assign footfall: roughly 20 High, 20 Medium, 10 Low
    footfall_pool = (["High"] * 20 + ["Medium"] * 20 + ["Low"] * 10)
    random.shuffle(footfall_pool)

    # Mark ~6 High-footfall machines as recovery candidates (intentionally low sales later)
    recovery_machines = set()
    high_indices = [i for i, f in enumerate(footfall_pool) if f == "High"]
    for i in random.sample(high_indices, 6):
        recovery_machines.add(MACHINE_IDS[i])

    for i, mid in enumerate(MACHINE_IDS):
        tier = footfall_pool[i]
        if tier == "High":
            index = random.randint(70, 100)
        elif tier == "Medium":
            index = random.randint(35, 69)
        else:
            index = random.randint(5, 34)

        area = weighted_choice(AREA_TYPES, AREA_TYPE_WEIGHTS)
        location = weighted_choice(REGIONS, REGION_WEIGHTS)
        rows.append({
            "machine_id": mid,
            "location": location,
            "area_type": area,
            "footfall_tier": tier,
            "footfall_index": index,
        })
    return rows, recovery_machines


# ─── Sales (seasonal) ────────────────────────────────────────────────────────

def seasonal_sku_weights(d: date):
    mults = SEASONAL_MULTIPLIERS[d.month]
    return [max(0.1, BASE_SKU_WEIGHTS[i] * mults[i]) for i in range(len(SKUS))]


def generate_sales(users, machine_rows, recovery_machines, n=20000):
    user_ids = [u["user_id"] for u in users]
    machine_location_map = {m["machine_id"]: m["location"] for m in machine_rows}

    rows = []
    sale_start = TODAY - timedelta(days=730)

    for _ in range(n):
        purchase_date = random_date(sale_start, TODAY)

        machine = random.choice(MACHINE_IDS)
        # Recovery machines get ~70% fewer sales to make the gap visible
        if machine in recovery_machines and random.random() < 0.7:
            machine = random.choice([m for m in MACHINE_IDS if m not in recovery_machines])

        rows.append({
            "sale_id": f"SAL-{uid()[:8].upper()}",
            "user_id": random.choice(user_ids),
            "sku": weighted_choice(SKUS, seasonal_sku_weights(purchase_date)),
            "purchase_date": purchase_date.isoformat(),
            "machine_id": machine,
            "machine_location": machine_location_map[machine],
        })
    return rows


# ─── App Interactions ─────────────────────────────────────────────────────────

def generate_interactions(users, n=3000):
    user_ids = [u["user_id"] for u in users]
    rows = []
    event_start = TODAY - timedelta(days=730)

    for _ in range(n):
        event_type = weighted_choice(EVENT_TYPES, EVENT_WEIGHTS)
        campaign_id = ""
        campaign_name = ""
        if event_type == "EngagedCampaign":
            camp = random.choice(CAMPAIGNS)
            campaign_id, campaign_name = camp

        rows.append({
            "interaction_id": f"INT-{uid()[:8].upper()}",
            "user_id": random.choice(user_ids),
            "event_type": event_type,
            "campaign_id": campaign_id,
            "campaign_name": campaign_name,
            "event_date": random_date(event_start, TODAY).isoformat(),
        })
    return rows


# ─── User Metrics (pre-computed from sales) ───────────────────────────────────

def generate_user_metrics(users, sales):
    cutoff_30 = TODAY - timedelta(days=30)
    cutoff_90 = TODAY - timedelta(days=90)

    # Index sales by user
    user_purchase_dates = defaultdict(list)
    for s in sales:
        d = date.fromisoformat(s["purchase_date"])
        user_purchase_dates[s["user_id"]].append(d)

    rows = []
    for u in users:
        uid_val = u["user_id"]
        dates = sorted(user_purchase_dates.get(uid_val, []))

        total = len(dates)
        p30 = sum(1 for d in dates if d >= cutoff_30)
        p90 = sum(1 for d in dates if d >= cutoff_90)

        if dates:
            last_purchase = max(dates)
            days_since = (TODAY - last_purchase).days
            if len(dates) >= 2:
                gaps = [(dates[i+1] - dates[i]).days for i in range(len(dates)-1)]
                avg_gap = round(sum(gaps) / len(gaps), 1)
            else:
                avg_gap = 180.0
        else:
            last_purchase = None
            days_since = 999
            avg_gap = 999.0

        # Churn risk: high days_since + big drop in purchase rate
        # Normalise days_since to 0-100 (0=today, 100=180+ days)
        days_score = min(100, days_since / 1.8)
        # Drop score: compare p30 to expected p30 from p90 rate
        expected_p30 = (p90 / 3) if p90 > 0 else 0
        drop_ratio = 1.0 - (p30 / expected_p30) if expected_p30 > 0 else (1.0 if days_since > 30 else 0.0)
        drop_score = clamp(drop_ratio * 100, 0, 100)

        churn_score = round(0.6 * days_score + 0.4 * drop_score)
        if churn_score >= 70:
            churn_tier = "High"
        elif churn_score >= 40:
            churn_tier = "Medium"
        else:
            churn_tier = "Low"

        rows.append({
            "user_id": uid_val,
            "last_purchase_date": last_purchase.isoformat() if last_purchase else "",
            "days_since_last_purchase": days_since,
            "total_purchases": total,
            "purchases_30d": p30,
            "purchases_90d": p90,
            "avg_days_between_purchases": avg_gap,
            "churn_risk_score": churn_score,
            "churn_risk_tier": churn_tier,
        })
    return rows


# ─── Campaign Segment Performance (pre-aggregated) ────────────────────────────

def generate_campaign_segment_performance(users, interactions):
    """
    Pre-aggregate campaign engagement by AgeGroup × Gender × Quarter.
    Uses affinities to ensure meaningful segment differentiation.
    """
    # Build user lookup
    user_lookup = {u["user_id"]: u for u in users}

    # Count actual engagements from interaction data
    counts = defaultdict(lambda: {"count": 0, "users": set()})
    for ev in interactions:
        if ev["event_type"] != "EngagedCampaign" or not ev["campaign_id"]:
            continue
        user = user_lookup.get(ev["user_id"])
        if not user:
            continue
        ag = age_group(int(user["age"]))
        gdr = user["gender"]
        quarter = quarter_label(date.fromisoformat(ev["event_date"]))
        key = (ev["campaign_id"], ev["campaign_name"], ag, gdr, quarter)
        counts[key]["count"] += 1
        counts[key]["users"].add(ev["user_id"])

    # For sparse cells, synthesise plausible numbers using affinity weights
    quarters = [
        "2024-Q1", "2024-Q2", "2024-Q3", "2024-Q4",
        "2025-Q1", "2025-Q2", "2025-Q3", "2025-Q4",
        "2026-Q1",
    ]
    rows = []
    for camp_id, camp_name in CAMPAIGNS:
        age_affinities = CAMPAIGN_AGE_AFFINITY[camp_id]
        gender_affinities = CAMPAIGN_GENDER_AFFINITY[camp_id]

        for ag_idx, ag in enumerate(AGE_GROUPS):
            for gdr_idx, gdr in enumerate(GENDERS):
                for quarter in quarters:
                    key = (camp_id, camp_name, ag, gdr, quarter)
                    actual = counts.get(key, {})
                    actual_count = actual.get("count", 0)
                    actual_users = len(actual.get("users", set()))

                    # Synthesise baseline from affinities if actual count is sparse
                    affinity = age_affinities[ag_idx] * gender_affinities[gdr_idx]
                    base = max(actual_count, int(random.gauss(affinity * 18, affinity * 5)))
                    base = max(1, base)
                    unique = max(actual_users, max(1, int(base * random.uniform(0.7, 0.95))))
                    engagement_rate = round(unique / max(unique + random.randint(10, 60), 1), 3)

                    rows.append({
                        "campaign_id": camp_id,
                        "campaign_name": camp_name,
                        "age_group": ag,
                        "gender": gdr,
                        "quarter": quarter,
                        "engagement_count": base,
                        "unique_users": unique,
                        "engagement_rate": engagement_rate,
                    })
    return rows


# ─── Write CSVs ──────────────────────────────────────────────────────────────

def write_csv(filename, rows, fieldnames):
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  Wrote {len(rows):,} rows → {filename}")


# ─── PostgreSQL Schema ────────────────────────────────────────────────────────

def generate_schema_sql():
    sql = """\
-- Coke ON Analytics POC — PostgreSQL schema for Supabase
-- Run this in the Supabase SQL Editor before importing CSVs.

CREATE TABLE IF NOT EXISTS users (
    user_id       TEXT PRIMARY KEY,
    join_date     DATE NOT NULL,
    age           INTEGER NOT NULL,
    gender        TEXT NOT NULL,
    region        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS machines (
    machine_id     TEXT PRIMARY KEY,
    location       TEXT NOT NULL,
    area_type      TEXT NOT NULL,
    footfall_tier  TEXT NOT NULL,
    footfall_index INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sales (
    sale_id          TEXT PRIMARY KEY,
    user_id          TEXT NOT NULL,
    sku              TEXT NOT NULL,
    purchase_date    DATE NOT NULL,
    machine_id       TEXT NOT NULL,
    machine_location TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_interactions (
    interaction_id TEXT PRIMARY KEY,
    user_id        TEXT NOT NULL,
    event_type     TEXT NOT NULL,
    campaign_id    TEXT,
    campaign_name  TEXT,
    event_date     DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS user_metrics (
    user_id                    TEXT PRIMARY KEY,
    last_purchase_date         DATE,
    days_since_last_purchase   INTEGER NOT NULL,
    total_purchases            INTEGER NOT NULL,
    purchases_30d              INTEGER NOT NULL,
    purchases_90d              INTEGER NOT NULL,
    avg_days_between_purchases NUMERIC NOT NULL,
    churn_risk_score           NUMERIC NOT NULL,
    churn_risk_tier            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS campaign_segment_performance (
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

TRUNCATE TABLE campaign_segment_performance, user_metrics, app_interactions, sales, machines, users RESTART IDENTITY CASCADE;
"""
    with open("schema.sql", "w", encoding="utf-8") as f:
        f.write(sql)
    print("  Wrote schema.sql")


if __name__ == "__main__":
    print("Generating synthetic Coke ON data...")

    users = generate_users(500)
    write_csv("users.csv", users, ["user_id", "join_date", "age", "gender", "region"])

    machine_rows, recovery_machines = generate_machines()
    write_csv(
        "machines.csv",
        machine_rows,
        ["machine_id", "location", "area_type", "footfall_tier", "footfall_index"],
    )

    sales = generate_sales(users, machine_rows, recovery_machines, 20000)
    write_csv(
        "sales.csv",
        sales,
        ["sale_id", "user_id", "sku", "purchase_date", "machine_id", "machine_location"],
    )

    interactions = generate_interactions(users, 3000)
    write_csv(
        "app_interactions.csv",
        interactions,
        ["interaction_id", "user_id", "event_type", "campaign_id", "campaign_name", "event_date"],
    )

    user_metrics = generate_user_metrics(users, sales)
    write_csv(
        "user_metrics.csv",
        user_metrics,
        [
            "user_id", "last_purchase_date", "days_since_last_purchase", "total_purchases",
            "purchases_30d", "purchases_90d", "avg_days_between_purchases",
            "churn_risk_score", "churn_risk_tier",
        ],
    )

    campaign_perf = generate_campaign_segment_performance(users, interactions)
    write_csv(
        "campaign_segment_performance.csv",
        campaign_perf,
        [
            "campaign_id", "campaign_name", "age_group", "gender", "quarter",
            "engagement_count", "unique_users", "engagement_rate",
        ],
    )

    generate_schema_sql()

    print(f"\nDone. Run schema.sql in Supabase SQL Editor, then import the 6 CSV files.")
    print(f"Recovery-opportunity machines (high footfall, low sales): {sorted(recovery_machines)}")
