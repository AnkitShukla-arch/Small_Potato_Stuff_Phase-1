"""Source 1/5 — MySQL: Colleges/Institutes.

Simulates the AICTE-adjacent institutes master list: one big relational table,
mostly well-maintained, with a handful of copy-paste errors.
"""
from __future__ import annotations

import json
import os
import random
import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pymysql

from seed import db_utils
from seed.conflicts_log import add as log_conflict
from seed.name_noise_utils import noisy_variant

db_utils.load_env()

NOW = date(2026, 8, 16)
CONFLICTS_PATH = PROJECT_ROOT / "conflicts_seeded.json"
DUPLICATE_COUNT = 9  # within-source duplicates to plant

CREATE_SQL = """
CREATE TABLE institutes (
  id INT AUTO_INCREMENT PRIMARY KEY,
  AICTE_Code VARCHAR(20) NOT NULL,
  Institute_Name VARCHAR(255) NOT NULL,
  State VARCHAR(60),
  District VARCHAR(60),
  Institute_Type VARCHAR(20),
  Approval_Status VARCHAR(20),
  Year_Established INT,
  Last_Updated DATE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""


def _connect():
    return pymysql.connect(
        host=os.environ["MYSQL_HOST"],
        port=int(os.environ["MYSQL_PORT"]),
        user=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
        database=os.environ["MYSQL_DATABASE"],
        autocommit=True,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def _plant_duplicates(cur, institutes, rng) -> list[dict]:
    """Plant 9 within-source duplicates and log each one."""
    planted = []
    for k in range(DUPLICATE_COUNT):
        src = institutes[rng.randrange(len(institutes))]
        code = src["aicte_code"]
        dup_id = f"mysql_dup_{k + 1:02d}"
        if k % 3 == 0:
            # same AICTE_Code reused, name spelled differently
            name_b = noisy_variant(src["name"], rng, min_transforms=2, max_transforms=3)
            cur.execute(
                "INSERT INTO institutes (AICTE_Code, Institute_Name, State, District, Institute_Type, Approval_Status, Year_Established, Last_Updated) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (code, name_b, src["state"], src["district"], src["type"], src["approval_status"], src["year_established"], NOW - timedelta(days=rng.randint(0, 90))),
            )
            log_conflict(CONFLICTS_PATH, {
                "type": "within_source_duplicate", "source": "mysql", "id": dup_id,
                "description": "Same AICTE_Code reused for a second row with a differently-spelled name (copy-paste error)",
                "institutes": [src["name"]],
                "detail": {"aicte_code": code, "name_a": src["name"], "name_b": name_b},
            })
        elif k % 3 == 1:
            # copy-paste row: identical except Last_Updated differs
            cur.execute(
                "INSERT INTO institutes (AICTE_Code, Institute_Name, State, District, Institute_Type, Approval_Status, Year_Established, Last_Updated) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (code, src["name"], src["state"], src["district"], src["type"], src["approval_status"], src["year_established"], NOW - timedelta(days=rng.randint(1, 14))),
            )
            log_conflict(CONFLICTS_PATH, {
                "type": "within_source_duplicate", "source": "mysql", "id": dup_id,
                "description": "Copy-paste duplicate row; only Last_Updated differs",
                "institutes": [src["name"]],
                "detail": {"aicte_code": code, "name": src["name"]},
            })
        else:
            # exact duplicate row
            cur.execute(
                "INSERT INTO institutes (AICTE_Code, Institute_Name, State, District, Institute_Type, Approval_Status, Year_Established, Last_Updated) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (code, src["name"], src["state"], src["district"], src["type"], src["approval_status"], src["year_established"], NOW - timedelta(days=rng.randint(0, 90))),
            )
            log_conflict(CONFLICTS_PATH, {
                "type": "within_source_duplicate", "source": "mysql", "id": dup_id,
                "description": "Exact duplicate row (identical field values)",
                "institutes": [src["name"]],
                "detail": {"aicte_code": code, "name": src["name"]},
            })
        planted.append(dup_id)
    return planted


def main() -> None:
    rng = random.Random(20260816 + 1)
    registry = json.loads((PROJECT_ROOT / "institute_registry.json").read_text(encoding="utf-8"))
    institutes = registry["institutes"]

    # conflict carriers keep their canonical name so cross-source
    # contradictions are actually detectable after normalization
    plan = registry["conflict_plan"]
    plan_carriers = {n for lst in plan.values() for n in lst}

    if not db_utils.wait_mysql():
        print("[mysql] ERROR: could not reach MySQL. Is it up? (docker compose up -d)")
        sys.exit(1)

    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS institutes")
            cur.execute(CREATE_SQL)
            inserted = 0
            noisy_count = 0
            for inst in institutes:
                name = inst["name"]
                if inst["name"] not in plan_carriers and rng.random() < 0.15:
                    name = noisy_variant(name, rng)
                    noisy_count += 1
                cur.execute(
                    "INSERT INTO institutes (AICTE_Code, Institute_Name, State, District, Institute_Type, Approval_Status, Year_Established, Last_Updated) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (inst["aicte_code"], name, inst["state"], inst["district"], inst["type"], inst["approval_status"], inst["year_established"], NOW - timedelta(days=rng.randint(0, 90))),
                )
                inserted += 1

            planted = _plant_duplicates(cur, institutes, rng)

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM institutes")
            total = cur.fetchone()["c"]

        print("=" * 60)
        print(f"[mysql] source: aicte_institutes.institutes ({os.environ['MYSQL_HOST']}:{os.environ['MYSQL_PORT']})")
        print(f"[mysql] institutes seeded        : {inserted}  (name-noisy rows: {noisy_count})")
        print(f"[mysql] within-source duplicates: {len(planted)}")
        print(f"[mysql] total rows in table     : {total}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
