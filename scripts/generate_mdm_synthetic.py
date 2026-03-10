#!/usr/bin/env python3
"""Generate synthetic MDM dataset per scenario.md.

Produces three source-system CSVs with intentional duplicates and anomalies:
- CRM (crm_contacts): 20k rows, names/emails with variations
- Billing (billing_accounts): 15k rows, abbreviated names, phone with country code
- Support (support_users): 25k rows, multiple accounts per person, typos

Output: data/raw/{crm,billing,support}/%Y/%m/%Y%m%d.csv
"""

from __future__ import annotations

import argparse
import csv
import logging
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TypeAlias

from faker import Faker

logger = logging.getLogger(__name__)

# --- Scenario.md constants ---------------------------------------------------

DEFAULT_OUTPUT_DIR = Path("data/raw")
DEFAULT_SEED: int | None = 42

# Target row counts (scenario §7)
CRM_ROW_COUNT = 20_000
BILLING_ROW_COUNT = 15_000
SUPPORT_ROW_COUNT = 25_000
# Unique customers after deduplication (~18k)
UNIQUE_CUSTOMER_COUNT = 18_000

# Missing rates (scenario §5.5)
EMAIL_MISSING_RATE_MIN = 0.10
EMAIL_MISSING_RATE_MAX = 0.15
PHONE_MISSING_RATE = 0.10
ADDRESS_MISSING_RATE = 0.20

# Duplicate rates (scenario §6)
CROSS_SYSTEM_DUPLICATE_RATE_MIN = 0.30
CROSS_SYSTEM_DUPLICATE_RATE_MAX = 0.40
INTRA_SYSTEM_DUPLICATE_RATE_MIN = 0.10
INTRA_SYSTEM_DUPLICATE_RATE_MAX = 0.15

# Plan types for billing
PLAN_TYPES = ("Basic", "Standard", "Premium", "Family", "Enterprise")

# Keyboard neighbors for typo simulation
KEYBOARD_NEIGHBORS: dict[str, tuple[str, ...]] = {
    "a": ("s", "q", "w"),
    "e": ("r", "w", "d"),
    "i": ("o", "u", "k"),
    "o": ("i", "p", "l"),
    "u": ("y", "i", "j"),
    "s": ("a", "d", "w"),
    ".": (".", ",", "m"),
    "@": ("@", "2", "q"),
}

# First-name variants (nickname ↔ formal) for name variation
FIRST_NAME_VARIANTS: dict[str, list[str]] = {
    "Jonathan": ["Jon", "John", "Jonathan", "J."],
    "John": ["Jon", "John", "Jonathan", "J."],
    "Jon": ["Jon", "John", "Jonathan", "J."],
    "Michael": ["Mike", "Michael", "M."],
    "Mike": ["Mike", "Michael", "M."],
    "Robert": ["Bob", "Rob", "Robert", "R."],
    "Bob": ["Bob", "Rob", "Robert", "R."],
    "William": ["Will", "Bill", "William", "W."],
    "James": ["Jim", "Jamie", "James", "J."],
    "Christopher": ["Chris", "Christopher", "C."],
    "Daniel": ["Dan", "Danny", "Daniel", "D."],
    "Matthew": ["Matt", "Matthew", "M."],
    "David": ["Dave", "David", "D."],
    "Joseph": ["Joe", "Joseph", "J."],
    "Andrew": ["Andy", "Drew", "Andrew", "A."],
    "Elizabeth": ["Liz", "Beth", "Eliza", "Elizabeth", "E."],
    "Jennifer": ["Jen", "Jenny", "Jennifer", "J."],
    "Margaret": ["Meg", "Peggy", "Margaret", "M."],
    "Katherine": ["Kate", "Kathy", "Katherine", "K."],
    "Catherine": ["Kate", "Cathy", "Catherine", "C."],
}

Rng: TypeAlias = random.Random


def _resolve_first_name_variants(first: str) -> list[str]:
    """Return list of possible first-name variants (nicknames/abbrev)."""
    for k, v in FIRST_NAME_VARIANTS.items():
        if k.lower() == first.lower():
            return v
    return [first, first[0] + ".", first[0] + first[1:].lower() if len(first) > 1 else first]


def _apply_typo(text: str, rng: Rng, prob: float = 0.03) -> str:
    """Apply a single character typo (neighbor or deletion) with given probability."""
    if not text or rng.random() >= prob:
        return text
    i = rng.randint(0, len(text) - 1)
    c = text[i]
    if rng.random() < 0.3 and len(text) > 1:
        return text[:i] + text[i + 1 :]
    if c in KEYBOARD_NEIGHBORS:
        new_c = rng.choice(KEYBOARD_NEIGHBORS[c])
        return text[:i] + new_c + text[i + 1 :]
    return text


def _format_phone_variant(phone_digits: str, rng: Rng) -> str:
    """Return one of the scenario §5.3 phone formats (Philippines-style)."""
    # Normalize to digits only for formatting
    digits = "".join(c for c in phone_digits if c.isdigit())
    if len(digits) < 10:
        digits = digits.zfill(10)
    if len(digits) > 10:
        digits = digits[-10:]
    fmt = rng.choice(
        [
            lambda: "0" + digits,
            lambda: digits,
            lambda: "+63" + digits,
            lambda: "+63 " + digits[:3] + " " + digits[3:6] + " " + digits[6:],
        ]
    )
    return fmt()


def _maybe_drop(value: str, missing_rate: float, rng: Rng) -> str:
    """Return value or empty string with given probability."""
    return "" if value and rng.random() < missing_rate else (value or "")


@dataclass(frozen=True, slots=True)
class CanonicalPerson:
    """One canonical customer; may appear in multiple systems with variations."""

    person_id: int
    first_name: str
    last_name: str
    email: str
    phone_digits: str
    address: str
    city: str
    country: str


def _generate_canonical_persons(
    count: int,
    fake: Faker,
    rng: Rng,
) -> list[CanonicalPerson]:
    """Generate count canonical persons with Faker; unique emails."""
    seen_emails: set[str] = set()
    persons: list[CanonicalPerson] = []
    while len(persons) < count:
        first = fake.first_name()
        last = fake.last_name()
        email = fake.email()
        if email in seen_emails:
            continue
        seen_emails.add(email)
        raw_addr = fake.address()
        address = " ".join(raw_addr.replace("\n", " ").split())
        # US-style phone; we'll format per-system
        phone = fake.numerify(text="##########")
        if len(phone) < 10:
            phone = phone.zfill(10)
        city = fake.city()
        country = fake.country_code()
        persons.append(
            CanonicalPerson(
                person_id=len(persons),
                first_name=first,
                last_name=last,
                email=email,
                phone_digits=phone,
                address=address,
                city=city,
                country=country,
            )
        )
    return persons


def _name_variant_crm(person: CanonicalPerson, rng: Rng) -> tuple[str, str]:
    """CRM: first_name, last_name; may use nickname."""
    variants = _resolve_first_name_variants(person.first_name)
    first = rng.choice(variants)
    return (first, person.last_name)


def _name_variant_billing(person: CanonicalPerson, rng: Rng) -> str:
    """Billing: account_name; may be abbreviated (e.g. J. Smith)."""
    variants = _resolve_first_name_variants(person.first_name)
    first = rng.choice(variants)
    if rng.random() < 0.3:
        last_abbrev = person.last_name[0] + "." if len(person.last_name) > 1 else person.last_name
        return f"{first} {last_abbrev}"
    return f"{first} {person.last_name}"


def _name_variant_support(person: CanonicalPerson, rng: Rng) -> str:
    """Support: single name field; full name with possible typo."""
    first = rng.choice(_resolve_first_name_variants(person.first_name))
    full = f"{first} {person.last_name}"
    return _apply_typo(full, rng, prob=0.02)


def _email_variant(person: CanonicalPerson, rng: Rng, missing_rate: float) -> str:
    """Email with optional typo and missing rate."""
    if rng.random() < missing_rate:
        return ""
    base = person.email
    if rng.random() < 0.08:
        base = _apply_typo(base, rng, prob=0.04)
    return base


def _phone_variant(person: CanonicalPerson, rng: Rng, missing_rate: float) -> str:
    """Formatted phone with scenario formats and missing rate."""
    if rng.random() < missing_rate:
        return ""
    return _format_phone_variant(person.phone_digits, rng)


def _address_variant(person: CanonicalPerson, rng: Rng, missing_rate: float) -> str:
    """Address with optional abbreviation and missing rate."""
    if rng.random() < missing_rate:
        return ""
    addr = person.address
    if "Street" in addr and rng.random() < 0.3:
        addr = addr.replace("Street", "St")
    if " Avenue" in addr and rng.random() < 0.3:
        addr = addr.replace(" Avenue", " Ave")
    return addr


def _build_crm_rows(
    persons: list[CanonicalPerson],
    row_count: int,
    intra_duplicate_rate: float,
    partition_date: date,
    rng: Rng,
) -> tuple[list[dict[str, str]], set[int]]:
    """Build crm_contacts rows (20k target). Returns (rows, set of person indices in CRM)."""
    email_miss = rng.uniform(EMAIL_MISSING_RATE_MIN, EMAIL_MISSING_RATE_MAX)
    phone_miss = PHONE_MISSING_RATE
    addr_miss = ADDRESS_MISSING_RATE

    # How many distinct persons in CRM; rest are intra duplicates
    num_duplicate_rows = int(row_count * intra_duplicate_rate)
    num_primary = row_count - num_duplicate_rows
    chosen_ids = list(rng.choices(range(len(persons)), k=num_primary))
    duplicate_ids = list(rng.choices(chosen_ids, k=num_duplicate_rows))
    all_person_indices = chosen_ids + duplicate_ids
    crm_person_indices = set(chosen_ids)
    rng.shuffle(all_person_indices)

    rows: list[dict[str, str]] = []
    base_dt = datetime(partition_date.year, partition_date.month, partition_date.day)
    for i, idx in enumerate(all_person_indices):
        person = persons[idx]
        first, last = _name_variant_crm(person, rng)
        crm_contact_id = f"CRM{i + 1:05d}"
        created = (base_dt + timedelta(seconds=i)).date()
        rows.append(
            {
                "crm_contact_id": crm_contact_id,
                "first_name": first,
                "last_name": last,
                "email": _maybe_drop(_email_variant(person, rng, 0.0), email_miss, rng),
                "phone": _maybe_drop(_phone_variant(person, rng, 0.0), phone_miss, rng),
                "address": _maybe_drop(_address_variant(person, rng, 0.0), addr_miss, rng),
                "city": person.city,
                "country": person.country,
                "created_date": created.isoformat(),
            }
        )
    return rows, crm_person_indices


def _build_billing_rows(
    persons: list[CanonicalPerson],
    row_count: int,
    cross_system_ids: set[int],
    cross_rate: float,
    partition_date: date,
    rng: Rng,
) -> list[dict[str, str]]:
    """Build billing_accounts rows (15k). cross_rate of rows use persons in cross_system_ids."""
    num_cross = int(row_count * cross_rate)
    num_other = row_count - num_cross
    cross_list = [i for i in cross_system_ids if i < len(persons)]
    if not cross_list:
        cross_list = list(range(min(len(persons), row_count)))
    other_indices = [i for i in range(len(persons)) if i not in cross_system_ids]
    if len(other_indices) < num_other:
        other_indices = list(range(len(persons)))
    chosen_cross = list(rng.choices(cross_list, k=num_cross))
    chosen_other = list(rng.choices(other_indices, k=num_other))
    all_indices = chosen_cross + chosen_other
    rng.shuffle(all_indices)

    email_miss = rng.uniform(EMAIL_MISSING_RATE_MIN, EMAIL_MISSING_RATE_MAX)
    phone_miss = PHONE_MISSING_RATE
    addr_miss = ADDRESS_MISSING_RATE

    rows = []
    for i, idx in enumerate(all_indices):
        person = persons[idx]
        billing_customer_id = f"B{i + 1:04d}"
        account_name = _name_variant_billing(person, rng)
        plan = rng.choice(PLAN_TYPES)
        start = partition_date - timedelta(days=rng.randint(30, 800))
        rows.append(
            {
                "billing_customer_id": billing_customer_id,
                "account_name": account_name,
                "billing_email": _maybe_drop(_email_variant(person, rng, 0.0), email_miss, rng),
                "phone": _maybe_drop(_phone_variant(person, rng, 0.0), phone_miss, rng),
                "billing_address": _maybe_drop(_address_variant(person, rng, 0.0), addr_miss, rng),
                "city": person.city,
                "country": person.country,
                "plan_type": plan,
                "account_start_date": start.isoformat(),
            }
        )
    return rows


def _build_support_rows(
    persons: list[CanonicalPerson],
    row_count: int,
    cross_system_ids: set[int],
    cross_rate: float,
    intra_duplicate_rate: float,
    partition_date: date,
    rng: Rng,
) -> list[dict[str, str]]:
    """Build support_users rows (25k). Cross and intra duplicate rates applied."""
    num_cross = int(row_count * cross_rate)
    num_other = row_count - num_cross
    cross_list = [i for i in cross_system_ids if i < len(persons)]
    if not cross_list:
        cross_list = list(range(min(len(persons), row_count)))
    other_indices = [i for i in range(len(persons))]
    chosen_cross = list(rng.choices(cross_list, k=num_cross))
    chosen_other = list(rng.choices(other_indices, k=num_other))
    all_indices = chosen_cross + chosen_other
    rng.shuffle(all_indices)

    email_miss = rng.uniform(EMAIL_MISSING_RATE_MIN, EMAIL_MISSING_RATE_MAX)
    phone_miss = PHONE_MISSING_RATE

    rows = []
    for i, idx in enumerate(all_indices):
        person = persons[idx]
        support_user_id = f"S{i + 1:04d}"
        name = _name_variant_support(person, rng)
        signup = partition_date - timedelta(days=rng.randint(1, 400))
        rows.append(
            {
                "support_user_id": support_user_id,
                "name": name,
                "email": _maybe_drop(_email_variant(person, rng, 0.0), email_miss, rng),
                "phone": _maybe_drop(_phone_variant(person, rng, 0.0), phone_miss, rng),
                "signup_date": signup.isoformat(),
            }
        )
    return rows


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def generate(
    output_dir: Path,
    partition_date: date,
    seed: int | None,
    crm_rows: int,
    billing_rows: int,
    support_rows: int,
    unique_customers: int,
    cross_rate_min: float,
    cross_rate_max: float,
    intra_rate_min: float,
    intra_rate_max: float,
) -> None:
    """Generate CRM, Billing, and Support CSVs per scenario.md."""
    rng = random.Random(seed)
    fake = Faker(seed=seed) if seed is not None else Faker()

    logger.info("Generating %d canonical persons", unique_customers)
    persons = _generate_canonical_persons(unique_customers, fake, rng)

    cross_rate = rng.uniform(cross_rate_min, cross_rate_max)
    intra_crm = rng.uniform(intra_rate_min, intra_rate_max)
    intra_support = rng.uniform(intra_rate_min, intra_rate_max)

    # CRM first; set of person_ids that appear in CRM (for cross-system overlap)
    crm_row_list, crm_person_indices = _build_crm_rows(
        persons, crm_rows, intra_crm, partition_date, rng
    )
    crm_columns = [
        "crm_contact_id",
        "first_name",
        "last_name",
        "email",
        "phone",
        "address",
        "city",
        "country",
        "created_date",
    ]

    year = partition_date.strftime("%Y")
    month = partition_date.strftime("%m")
    date_str = partition_date.strftime("%Y%m%d")

    crm_path = output_dir / "crm" / year / month / f"{date_str}.csv"
    _write_csv(crm_path, crm_columns, crm_row_list)
    logger.info("Wrote %s (%d rows)", crm_path, len(crm_row_list))

    billing_row_list = _build_billing_rows(
        persons, billing_rows, crm_person_indices, cross_rate, partition_date, rng
    )
    billing_path = output_dir / "billing" / year / month / f"{date_str}.csv"
    billing_columns = [
        "billing_customer_id",
        "account_name",
        "billing_email",
        "phone",
        "billing_address",
        "city",
        "country",
        "plan_type",
        "account_start_date",
    ]
    _write_csv(billing_path, billing_columns, billing_row_list)
    logger.info("Wrote %s (%d rows)", billing_path, len(billing_row_list))

    # Support cross-system: overlap with CRM
    support_row_list = _build_support_rows(
        persons, support_rows, crm_person_indices, cross_rate, intra_support, partition_date, rng
    )
    support_path = output_dir / "support" / year / month / f"{date_str}.csv"
    support_columns = ["support_user_id", "name", "email", "phone", "signup_date"]
    _write_csv(support_path, support_columns, support_row_list)
    logger.info("Wrote %s (%d rows)", support_path, len(support_row_list))

    logger.info(
        "MDM synthetic data complete: %d CRM, %d Billing, %d Support (~%d unique customers)",
        len(crm_row_list),
        len(billing_row_list),
        len(support_row_list),
        unique_customers,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate synthetic MDM dataset (CRM, Billing, Support) per scenario.md.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Base directory for output (default: %(default)s)",
    )
    parser.add_argument(
        "--date",
        type=lambda s: datetime.strptime(s, "%Y%m%d").date(),
        default=date.today(),
        help="Partition date YYYYMMDD (default: today)",
    )
    parser.add_argument(
        "--crm-rows",
        type=int,
        default=CRM_ROW_COUNT,
        help="Number of CRM rows (default: %(default)s)",
    )
    parser.add_argument(
        "--billing-rows",
        type=int,
        default=BILLING_ROW_COUNT,
        help="Number of Billing rows (default: %(default)s)",
    )
    parser.add_argument(
        "--support-rows",
        type=int,
        default=SUPPORT_ROW_COUNT,
        help="Number of Support rows (default: %(default)s)",
    )
    parser.add_argument(
        "--unique-customers",
        type=int,
        default=UNIQUE_CUSTOMER_COUNT,
        help="Unique canonical customers (default: %(default)s)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help="Random seed (default: %(default)s)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    return parser.parse_args()


def main() -> None:
    """CLI entrypoint."""
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    if args.unique_customers < 1:
        logger.error("--unique-customers must be >= 1")
        raise SystemExit(1)
    if args.crm_rows < 1 or args.billing_rows < 1 or args.support_rows < 1:
        logger.error("Row counts must be >= 1")
        raise SystemExit(1)

    generate(
        output_dir=args.output_dir,
        partition_date=args.date,
        seed=args.seed,
        crm_rows=args.crm_rows,
        billing_rows=args.billing_rows,
        support_rows=args.support_rows,
        unique_customers=args.unique_customers,
        cross_rate_min=CROSS_SYSTEM_DUPLICATE_RATE_MIN,
        cross_rate_max=CROSS_SYSTEM_DUPLICATE_RATE_MAX,
        intra_rate_min=INTRA_SYSTEM_DUPLICATE_RATE_MIN,
        intra_rate_max=INTRA_SYSTEM_DUPLICATE_RATE_MAX,
    )


if __name__ == "__main__":
    main()
