"""Source 3/5 — PostgreSQL (faculty_db): Faculty.

Separate database on the same Postgres instance as courses (different team,
different schema conventions). institute_ref is free text with the same
inconsistency pattern as courses.
"""
from __future__ import annotations

import json
import os
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import psycopg
from faker import Faker

from seed import db_utils
from seed.conflicts_log import add as log_conflict
from seed.name_noise_utils import noisy_variant

db_utils.load_env()

NOW = datetime(2026, 8, 16, 12, 0, 0)
CONFLICTS_PATH = PROJECT_ROOT / "conflicts_seeded.json"
TARGET_ROWS = 400
ORPHAN_FACULTY = 7  # faculty rows referencing institutes that don't exist in MySQL

CREATE_SQL = """
CREATE TABLE faculty (
  faculty_id SERIAL PRIMARY KEY,
  full_name VARCHAR(150),
  institute_ref VARCHAR(255),
  designation VARCHAR(40),
  qualification VARCHAR(20),
  department VARCHAR(80),
  date_joined DATE,
  updated_on TIMESTAMP
)
"""

DESIGNATIONS = ["Professor", "Assoc. Professor", "Asst. Professor"]
QUALIFICATIONS = ["PhD", "M.Tech", "M.E."]
DEPARTMENTS = ["CSE", "ECE", "MECH", "CIVIL", "IT", "EEE", "CHEM", "AIDS", "MBA", "Physics", "Mathematics"]

# Institutes that exist ONLY in this source (orphaned/legacy faculty records)
ORPHAN_INSTITUTES = [
    "Ganga Engineering Institute, Kanpur Dehat",
    "Shri Ram Polytechnic, Saharanpur",
    "Annapurna Institute of Technology, Mysuru",
    "Ratan Tata Engineering College, Mumbai Suburban",
    "Old Staff College of Engineering, Nagpur",
    "Dakshin Gujarat Institute, Surat East",
    "Jhansi Technical Institute, Jhansi",
]


def _connect():
    return psycopg.connect(
        host=os.environ["POSTGRES_HOST"],
        port=int(os.environ["POSTGRES_PORT"]),
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        dbname=os.environ["FACULTY_DB"],
        autocommit=True,
    )


def main() -> None:
    rng = random.Random(20260816 + 3)
    fake = Faker("en_IN")
    fake.seed_instance(20260816 + 3)
    registry = json.loads((PROJECT_ROOT / "institute_registry.json").read_text(encoding="utf-8"))
    institutes = registry["institutes"]
    all_names = [i["name"] for i in institutes]

    if not db_utils.wait_postgres():
        print("[postgres_faculty] ERROR: could not reach PostgreSQL. Is it up? (docker compose up -d)")
        sys.exit(1)

    conn = _connect()
    try:
        conn.execute("DROP TABLE IF EXISTS faculty")
        conn.execute(CREATE_SQL)

        # coverage asymmetry: only ~70% of institutes have faculty records
        covered = set(rng.sample(all_names, 105))
        inserted = 0
        while inserted < TARGET_ROWS:
            name = rng.choice(list(covered))
            ref = name
            if rng.random() < 0.20:
                ref = noisy_variant(name, rng)
            joined = datetime(2004, 1, 1) + timedelta(days=rng.randint(0, 365 * 20))
            updated = NOW - timedelta(days=rng.randint(400, 1900)) if rng.random() < 0.40 else NOW - timedelta(days=rng.randint(0, 120))
            conn.execute(
                "INSERT INTO faculty (full_name, institute_ref, designation, qualification, department, date_joined, updated_on) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (fake.name(), ref, rng.choice(DESIGNATIONS), rng.choice(QUALIFICATIONS), rng.choice(DEPARTMENTS), joined, updated),
            )
            inserted += 1

        # orphaned faculty rows (institute does not exist in MySQL)
        for k, inst_name in enumerate(ORPHAN_INSTITUTES):
            joined = datetime(2004, 1, 1) + timedelta(days=rng.randint(0, 365 * 20))
            conn.execute(
                "INSERT INTO faculty (full_name, institute_ref, designation, qualification, department, date_joined, updated_on) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (fake.name(), inst_name, rng.choice(DESIGNATIONS), rng.choice(QUALIFICATIONS), rng.choice(DEPARTMENTS), joined, NOW - timedelta(days=rng.randint(400, 1900))),
            )
            log_conflict(CONFLICTS_PATH, {
                "type": "orphaned_record", "source": "postgres:faculty_db", "id": f"pg_faculty_orphan_{k + 1:02d}",
                "description": "Faculty row references an institute that does not exist in the MySQL institutes table",
                "institutes": [inst_name],
            })

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM faculty")
            total = cur.fetchone()[0]
            cur.execute("SELECT COUNT(DISTINCT institute_ref) FROM faculty")
            distinct = cur.fetchone()[0]

        print("=" * 60)
        print(f"[postgres_faculty] source: faculty_db.faculty ({os.environ['POSTGRES_HOST']}:{os.environ['POSTGRES_PORT']})")
        print(f"[postgres_faculty] faculty rows seeded : {inserted}")
        print(f"[postgres_faculty] orphaned rows      : {len(ORPHAN_INSTITUTES)}")
        print(f"[postgres_faculty] total rows in table: {total}  (distinct institute_refs: {distinct})")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
