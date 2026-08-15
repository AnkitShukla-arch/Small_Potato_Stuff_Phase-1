"""Generate the canonical institute registry (internal single source of truth).

This file is used ONLY by the seeding layer. None of the five mock sources
expose it — each database keeps its own (noisy) representation of the same
real-world institutes, which is exactly the fragmentation being demonstrated.

Deterministic: fixed seed -> identical registry every run, so re-seeding is
idempotent and the planted conflicts stay stable across runs.

Output: institute_registry.json (project root)
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from faker import Faker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = PROJECT_ROOT / "institute_registry.json"

SEED = 20260816

# 12 states x 5 districts each (synthetic but realistic)
STATES_DISTRICTS = {
    "Andhra Pradesh": ["Anantapur", "Kurnool", "Guntur", "Kadapa", "Vizianagaram"],
    "Telangana": ["Warangal", "Karimnagar", "Nizamabad", "Khammam", "Adilabad"],
    "Tamil Nadu": ["Coimbatore", "Salem", "Thanjavur", "Vellore", "Tirunelveli"],
    "Karnataka": ["Belagavi", "Hubballi", "Mysuru", "Ballari", "Davanagere"],
    "Maharashtra": ["Nagpur", "Aurangabad", "Nashik", "Kolhapur", "Solapur"],
    "Gujarat": ["Rajkot", "Surat", "Vadodara", "Bhavnagar", "Junagadh"],
    "Uttar Pradesh": ["Lucknow", "Kanpur", "Varanasi", "Meerut", "Agra"],
    "Rajasthan": ["Jaipur", "Jodhpur", "Kota", "Udaipur", "Bikaner"],
    "Madhya Pradesh": ["Indore", "Bhopal", "Jabalpur", "Gwalior", "Ujjain"],
    "West Bengal": ["Kolkata", "Howrah", "Durgapur", "Kharagpur", "Siliguri"],
    "Odisha": ["Bhubaneswar", "Cuttack", "Rourkela", "Berhampur", "Sambalpur"],
    "Punjab": ["Ludhiana", "Amritsar", "Jalandhar", "Patiala", "Bathinda"],
}

NAME_PREFIXES = [
    "Shri", "Sri Venkateswara", "Guru Nanak", "Mahatma Gandhi", "Dr. B.R. Ambedkar",
    "Siddhartha", "Vasavi", "Vignan", "Malla Reddy", "Sreenidhi", "CVR", "Anurag",
    "Gokaraju", "K.S.R.", "Matrusri", "Sree Dattha", "Sri Indu", "Geethanjali",
    "Bapatla", "Lendi", "Sreyas", "Gandhi", "Aditya", "Srinivasa", "Raghu", "Vaagdevi",
    "Sree", "Kakatiya", "Andhra", "Sri Sathya Sai", "Chaitanya", "St. Mary's",
    "Sinhgad", "Vishwakarma", "Lokmanya", "Sardar", "BMS", "RV", "Nitte", "NMAM",
    "Manipal", "Karunya", "Amrita", "Thapar", "Galgotias", "SRM", "VIT", "PSG",
    "Kongu", "Kumaraguru", "Thiagarajar", "Kalasalingam", "Bharat", "Ideal",
]

SUFFIXES = [
    "College of Engineering",
    "Institute of Technology",
    "Engineering College",
    "Institute of Engineering and Technology",
    "College of Engineering and Technology",
    "Institute of Technology and Science",
    "Polytechnic",
]

GOVT_TEMPLATES = [
    "Government College of Engineering, {d}",
    "Government Polytechnic, {d}",
    "Government Engineering College, {d}",
]


def _make_name(rng: random.Random, itype: str, district: str) -> str:
    if itype == "Govt":
        return rng.choice(GOVT_TEMPLATES).format(d=district)
    if itype == "Autonomous":
        if rng.random() < 0.45:
            return f"National Institute of Technology, {district}"
        return f"{rng.choice(NAME_PREFIXES)} {rng.choice(SUFFIXES)}, {district}"
    return f"{rng.choice(NAME_PREFIXES)} {rng.choice(SUFFIXES)}, {district}"


def _by_name(institutes: list[dict], name: str) -> dict:
    for inst in institutes:
        if inst["name"] == name:
            return inst
    raise KeyError(name)


def _conflict_plan(institutes: list[dict], rng: random.Random) -> dict:
    """Deterministic picks of institutes that will carry cross-source conflicts.

    Each source script reads this plan and plants its side of the contradiction.
    """
    def pick(*idx: int) -> list[str]:
        return [institutes[i]["name"] for i in idx]

    closed = pick(3, 17, 29, 44, 61)          # Approved in MySQL, but listed in closed_institutes.csv
    unapproved = pick(9, 22, 51)              # Approved/Under Review in MySQL, but in unapproved_list.csv
    rejected = pick(13, 37)                   # Rejected in MySQL, yet has courses + a scholarship
    nba = pick(7, 33)                         # Under Review in MySQL, but NBA CSV says Accredited

    for name in closed:
        _by_name(institutes, name)["approval_status"] = "Approved"
    for name, status in zip(unapproved, ["Approved", "Approved", "Approved"]):
        _by_name(institutes, name)["approval_status"] = status
    for name in rejected:
        _by_name(institutes, name)["approval_status"] = "Rejected"
    for name in nba:
        _by_name(institutes, name)["approval_status"] = "Under Review"

    return {
        "approved_but_closed": closed,
        "approved_but_unapproved_listed": unapproved,
        "rejected_with_courses": rejected,
        "under_review_but_nba_accredited": nba,
    }


def build_registry(seed: int = SEED) -> dict:
    rng = random.Random(seed)
    fake = Faker("en_IN")
    fake.seed_instance(seed)

    states = list(STATES_DISTRICTS.keys())
    institutes: list[dict] = []
    used_names: set[str] = set()
    i = 0
    while len(institutes) < 150:
        state = states[i % len(states)]
        district = rng.choice(STATES_DISTRICTS[state])
        itype = rng.choices(["Private", "Govt", "Autonomous"], weights=[0.60, 0.25, 0.15])[0]
        name = _make_name(rng, itype, district)
        if name in used_names:
            for d2 in rng.sample(STATES_DISTRICTS[state], k=len(STATES_DISTRICTS[state])):
                candidate = _make_name(rng, itype, d2)
                if candidate not in used_names:
                    name = candidate
                    break
        if name in used_names:
            name = f"{name} {len(institutes) + 1}"
        used_names.add(name)

        approval = rng.choices(["Approved", "Under Review", "Rejected"], weights=[0.78, 0.15, 0.07])[0]
        institutes.append({
            "id": f"INST_{len(institutes):03d}",
            "name": name,
            "state": state,
            "district": district,
            "type": itype,
            "approval_status": approval,
            "year_established": rng.randint(1955, 2020),
            "aicte_code": f"{rng.randint(1, 8)}-{rng.randint(10**9, 10**10 - 1)}",
        })
        i += 1

    plan = _conflict_plan(institutes, rng)
    return {
        "seed": seed,
        "count": len(institutes),
        "conflict_plan": plan,
        "institutes": institutes,
    }


def main() -> None:
    data = build_registry()
    REGISTRY_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    plan = data["conflict_plan"]
    print("=" * 60)
    print(f"[registry] wrote {len(data['institutes'])} canonical institutes -> {REGISTRY_PATH.name}")
    print(f"[registry] cross-source conflict carriers:")
    print(f"            approved-but-closed            : {len(plan['approved_but_closed'])}")
    print(f"            approved-but-unapproved-listed : {len(plan['approved_but_unapproved_listed'])}")
    print(f"            rejected-but-has-courses       : {len(plan['rejected_with_courses'])}")
    print(f"            under-review-but-nba-accredited: {len(plan['under_review_but_nba_accredited'])}")
    print(f"[registry] total conflict carriers: {sum(len(v) for v in plan.values())}")


if __name__ == "__main__":
    main()
