"""Source 4/5 — MongoDB (aicte_scholarships): Scholarships & Schemes.

The point of Mongo here is schema flexibility: every document has a genuinely
different field set (eligibility keys vary, amount is sometimes a string and
sometimes a number, some docs are missing fields entirely).
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

from pymongo import MongoClient

from seed import db_utils
from seed.conflicts_log import add as log_conflict
from seed.name_noise_utils import noisy_variant

db_utils.load_env()

NOW = datetime(2026, 8, 16, 12, 0, 0)
CONFLICTS_PATH = PROJECT_ROOT / "conflicts_seeded.json"
TARGET_DOCS = 50
DUPLICATE_COUNT = 6  # within-source duplicate documents to plant
INSTITUTE_COVERAGE = 60  # ~40% of 150 institutes referenced by scholarships

SCHEMES = [
    ("Post Matric Scholarship for SC Students", "Ministry of Social Justice & Empowerment"),
    ("Central Sector Scheme of Scholarships for College and University Students", "Ministry of Education"),
    ("National Means-cum-Merit Scholarship", "Department of School Education"),
    ("AICTE Pragati Scholarship for Girls", "AICTE"),
    ("AICTE Saksham Scholarship for Differently Abled", "AICTE"),
    ("PG Scholarship for GATE/GPAT Qualified Students", "AICTE"),
    ("Swami Vivekananda Single Girl Child Scholarship", "AICTE"),
    ("Dr. Ambedkar Post-Matric Scholarship", "State Government"),
    ("EBC Post-Matric Scholarship", "State Government"),
    ("Minority Community Scholarship (MOMA)", "Ministry of Minority Affairs"),
    ("Indira Gandhi Scholarship for Single Girl Child", "Ministry of Education"),
    ("Kishore Vaigyanik Protsahan Yojana (KVPY)", "Department of Science & Technology"),
    ("Nirali Vidyarthini Scholarship", "State Government"),
    ("Chief Minister's Special Scholarship Scheme", "State Government"),
    ("Merit-cum-Means Scholarship", "State Government"),
    ("Telangana State Post-Matric Scholarship", "Telangana State Government"),
    ("Maharashtra State OBC Scholarship", "Maharashtra State Government"),
    ("Karnataka Vidyasiri Scheme", "Karnataka State Government"),
    ("Punjab Scholarship for Scheduled Castes", "Punjab State Government"),
    ("Gujarat Yuva Kaushal Scholarship", "Gujarat State Government"),
    ("Rajasthan Devnarayan Yojana", "Rajasthan State Government"),
    ("UP Pre-Matric Scholarship", "Uttar Pradesh State Government"),
    ("West Bengal Swami Vivekananda Merit-cum-Means", "West Bengal State Government"),
    ("Odisha e-Medhabruti Scholarship", "Odisha State Government"),
    ("Tamil Nadu CM's Merit Scholarship", "Tamil Nadu State Government"),
    ("Andhra Pradesh Vidya Deevena", "Andhra Pradesh State Government"),
    ("CSR-funded Engineering Scholarship", "Private Foundation / CSR"),
    ("Women in STEM Scholarship", "NGO / Corporate"),
    ("Green Energy Engineering Scholarship", "NGO / Corporate"),
    ("Tribal Development Engineering Scheme", "Tribal Welfare Department"),
    ("Backward Classes Post-Matric Scheme", "BC Welfare Department"),
    ("National Fellowship for OBC Students", "Ministry of Social Justice & Empowerment"),
    ("Incentive to Girl Students for Technical Education", "AICTE"),
    ("Special Scholarship for J&K Students", "Ministry of Home Affairs"),
    ("Rural Engineering Talent Scholarship", "NGO / Corporate"),
]

ELIGIBILITY_TEMPLATES = [
    {"income_limit": "₹2.5 lakh per annum"},
    {"income_limit": "₹4.5 lakh per annum"},
    {"category": ["SC"]},
    {"category": ["SC", "ST"]},
    {"category": ["OBC", "EWS"]},
    {"category": ["ST"]},
    {"min_percentage": "60% in class XII"},
    {"min_percentage": "75% in qualifying examination"},
    {"gender": "female"},
    {"income_limit": "₹1.8 lakh per annum", "category": ["SC", "ST", "OBC"]},
    {"income_limit": "₹3 lakh per annum", "min_percentage": "55%"},
    {"category": ["OBC", "EWS"], "min_percentage": "60%"},
    {},  # genuinely missing eligibility details
]

AMOUNTS = [
    "₹50,000",
    "₹1,00,000",
    "Up to ₹2,00,000",
    "Full tuition fee",
    "₹20,000 per year",
    "Tuition + hostel fee",
    "₹1,20,000",
    "Up to ₹8,000 per month",
    50000,
    120000,
    25000,
    40000,
]

STATES = [
    "Andhra Pradesh", "Telangana", "Tamil Nadu", "Karnataka", "Maharashtra",
    "Gujarat", "Uttar Pradesh", "Rajasthan", "Madhya Pradesh", "West Bengal",
    "Odisha", "Punjab", "All States",
]


def _build_doc(scheme, body, pool, rng) -> dict:
    doc = {
        "scheme_name": scheme,
        "administering_body": body,
        "last_updated": NOW - timedelta(days=rng.randint(0, 60)),
    }
    # eligibility: genuinely varied key sets
    doc["eligibility"] = dict(rng.choice(ELIGIBILITY_TEMPLATES))

    # applicable_states
    if rng.random() < 0.30:
        doc["applicable_states"] = ["All States"]
    else:
        doc["applicable_states"] = rng.sample([s for s in STATES if s != "All States"], rng.randint(1, 5))

    # applicable_institutes: ~40% of docs reference specific institutes, rest are general
    if rng.random() < 0.60 and pool:
        n = rng.randint(1, 4)
        refs = []
        for _ in range(n):
            inst = rng.choice(pool)
            refs.append(noisy_variant(inst, rng) if rng.random() < 0.30 else inst)
        doc["applicable_institutes"] = refs

    # amount: string OR number, varies by scheme
    if rng.random() < 0.85:
        doc["amount"] = rng.choice(AMOUNTS)

    # occasionally drop a field entirely (schema flexibility)
    if rng.random() < 0.12:
        doc.pop("eligibility", None)
    if rng.random() < 0.08:
        doc.pop("administering_body", None)
    return doc


def main() -> None:
    rng = random.Random(20260816 + 4)
    registry = json.loads((PROJECT_ROOT / "institute_registry.json").read_text(encoding="utf-8"))
    institutes = registry["institutes"]
    plan = registry["conflict_plan"]
    all_names = [i["name"] for i in institutes]

    if not db_utils.wait_mongo():
        print("[mongo] ERROR: could not reach MongoDB. Is it up? (docker compose up -d)")
        sys.exit(1)

    client = MongoClient(os.environ["MONGO_HOST"], int(os.environ["MONGO_PORT"]), serverSelectionTimeoutMS=5000)
    db = client[os.environ["MONGO_DB"]]
    coll = db["scholarships"]
    coll.drop()

    # ~40% institute coverage, always including the rejected-conflict institutes
    pool = set(rng.sample(all_names, INSTITUTE_COVERAGE))
    pool.update(plan["rejected_with_courses"])
    pool = list(pool)

    inserted = 0
    for i in range(TARGET_DOCS):
        scheme, body = SCHEMES[i % len(SCHEMES)]
        if i >= len(SCHEMES):
            scheme = f"{scheme} (State Special Extension {i // len(SCHEMES)})"
        coll.insert_one(_build_doc(scheme, body, pool, rng))
        inserted += 1

    # within-source duplicates: 6 docs (3 exact, 3 near)
    planted = []
    for k in range(DUPLICATE_COUNT):
        scheme, body = SCHEMES[rng.randrange(len(SCHEMES))]
        base = _build_doc(scheme, body, pool, rng)
        dup_id = f"mongo_dup_{k + 1:02d}"
        if k % 2 == 0:
            coll.insert_one(dict(base))  # exact duplicate
            desc = "Exact duplicate scholarship document"
        else:
            near = dict(base)
            if "amount" in near:
                near["amount"] = f"{near['amount']} (revised)"
            near["last_updated"] = NOW - timedelta(days=rng.randint(1, 30))
            coll.insert_one(near)
            desc = "Near-duplicate scholarship document (amount/date drift)"
        log_conflict(CONFLICTS_PATH, {
            "type": "within_source_duplicate", "source": "mongodb", "id": dup_id,
            "description": desc,
            "institutes": base.get("applicable_institutes", [])[:1],
            "detail": {"scheme_name": scheme},
        })
        planted.append(dup_id)

    # cross-source conflicts: scholarship applicable to institutes MySQL marks Rejected
    for k, name in enumerate(plan["rejected_with_courses"]):
        scheme, body = SCHEMES[rng.randrange(len(SCHEMES))]
        doc = _build_doc(scheme, body, pool, rng)
        doc["applicable_institutes"] = [name]
        coll.insert_one(doc)
        log_conflict(CONFLICTS_PATH, {
            "type": "cross_source_conflict", "source": "mongodb", "id": f"cs_rejected_scholarship_{k + 1:02d}",
            "description": "Scholarship document is applicable to an institute that MySQL marks Rejected",
            "institutes": [name],
            "sources": ["mysql", "mongodb"],
            "fields_involved": {"mysql.approval_status": "Rejected", "mongodb.scholarships.applicable_institutes": [name]},
        })

    total = coll.count_documents({})
    with_refs = coll.count_documents({"applicable_institutes": {"$exists": True}})

    print("=" * 60)
    print(f"[mongo] source: {os.environ['MONGO_DB']}.scholarships ({os.environ['MONGO_HOST']}:{os.environ['MONGO_PORT']})")
    print(f"[mongo] documents seeded          : {inserted}")
    print(f"[mongo] within-source duplicates  : {len(planted)}")
    print(f"[mongo] cross-source conflicts    : {len(plan['rejected_with_courses'])}")
    print(f"[mongo] total docs in collection  : {total}  (with institute refs: {with_refs})")
    client.close()


if __name__ == "__main__":
    main()
