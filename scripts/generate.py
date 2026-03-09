#!/usr/bin/env python3
"""Generate synthetic customer-like data for entity resolution across source systems.

Outputs partitioned CSVs under output_dir/<source>/%Y/%m/%Y%m%d.csv with intentional
noise (deletions, transpositions, extra characters) in name, email, and address.
"""

from __future__ import annotations

import argparse
import csv
import logging
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from faker import Faker

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_DIR = Path("data/raw")
DEFAULT_SOURCES = ("crm", "ticketing", "support", "billing", "marketing")
DEFAULT_NUM_ENTITIES = 200
DEFAULT_NOISE_PROB = 0.25
DEFAULT_MASTER_SOURCE = "crm"
DEFAULT_DAYS = 2
DEFAULT_MASTER_CHANGE_PROB = 0.3
CSV_COLUMNS = (
    "entity_id",
    "source_system",
    "source_record_id",
    "full_name",
    "email",
    "address",
    "phone",
    "created_at",
)

# Keyboard neighbors for plausible typo insertions (subset).
KEYBOARD_NEIGHBORS: dict[str, tuple[str, ...]] = {
    "a": ("s", "q", "w"),
    "e": ("r", "w", "d"),
    "i": ("o", "u", "k"),
    "o": ("i", "p", "l"),
    "u": ("y", "i", "j"),
    "s": ("a", "d", "w"),
    " ": (" ", "c", "v"),
    ".": (".", ",", "m"),
    "@": ("@", "2", "q"),
}


def _apply_deletion(text: str, rng: random.Random) -> str:
    """Remove one random character (if length allows)."""
    if len(text) <= 1:
        return text
    i = rng.randint(0, len(text) - 1)
    return text[:i] + text[i + 1 :]


def _apply_transposition(text: str, rng: random.Random) -> str:
    """Swap two adjacent characters."""
    if len(text) < 2:
        return text
    i = rng.randint(0, len(text) - 2)
    chars = list(text)
    chars[i], chars[i + 1] = chars[i + 1], chars[i]
    return "".join(chars)


def _apply_insertion(text: str, rng: random.Random) -> str:
    """Insert one extra character (duplicate or keyboard neighbor)."""
    if not text:
        return text
    i = rng.randint(0, len(text))
    char = text[i - 1] if i else text[0]
    if rng.random() < 0.5 and char in KEYBOARD_NEIGHBORS:
        insert = rng.choice(KEYBOARD_NEIGHBORS[char])
    else:
        insert = char
    return text[:i] + insert + text[i:]


def apply_noise(
    text: str,
    *,
    prob_deletion: float = 0.0,
    prob_transposition: float = 0.0,
    prob_insertion: float = 0.0,
    rng: random.Random | None = None,
) -> str:
    """Apply at most one type of noise to text, with given probabilities."""
    if not text or (prob_deletion <= 0 and prob_transposition <= 0 and prob_insertion <= 0):
        return text
    rng = rng or random.Random()
    roll = rng.random()
    if roll < prob_deletion:
        return _apply_deletion(text, rng)
    if roll < prob_deletion + prob_transposition:
        return _apply_transposition(text, rng)
    if roll < prob_deletion + prob_transposition + prob_insertion:
        return _apply_insertion(text, rng)
    return text


@dataclass(frozen=True, slots=True)
class CanonicalEntity:
    """One canonical person; same entity may appear in multiple sources with noise."""

    entity_id: str
    full_name: str
    email: str
    address: str
    phone: str


def _generate_canonical_entities(
    count: int,
    fake: Faker,
    rng: random.Random,
) -> list[CanonicalEntity]:
    """Generate count canonical entities with Faker."""
    seen_emails: set[str] = set()
    entities: list[CanonicalEntity] = []
    while len(entities) < count:
        full_name = fake.name()
        email = fake.email()
        if email in seen_emails:
            continue
        seen_emails.add(email)
        # Replace newlines in address for CSV
        raw_address = fake.address()
        address = " ".join(raw_address.replace("\n", " ").split())
        phone = fake.phone_number()
        entity_id = f"ent_{len(entities):06d}"
        entities.append(
            CanonicalEntity(
                entity_id=entity_id,
                full_name=full_name,
                email=email,
                address=address,
                phone=phone,
            ),
        )
    return entities


def _noisy_row(
    entity: CanonicalEntity,
    source_system: str,
    source_record_id: str,
    created_at: str,
    noise_prob: float,
    rng: random.Random,
) -> dict[str, str]:
    """Build one CSV row with optional noise on name, email, address."""
    prob_each = noise_prob / 3.0
    return {
        "entity_id": entity.entity_id,
        "source_system": source_system,
        "source_record_id": source_record_id,
        "full_name": apply_noise(
            entity.full_name,
            prob_deletion=prob_each,
            prob_transposition=prob_each,
            prob_insertion=prob_each,
            rng=rng,
        ),
        "email": apply_noise(
            entity.email,
            prob_deletion=prob_each,
            prob_transposition=prob_each,
            prob_insertion=prob_each,
            rng=rng,
        ),
        "address": apply_noise(
            entity.address,
            prob_deletion=prob_each,
            prob_transposition=prob_each,
            prob_insertion=prob_each,
            rng=rng,
        ),
        "phone": entity.phone,
        "created_at": created_at,
    }


def _write_partitioned_csv(
    output_dir: Path,
    partition_date: date,
    source_system: str,
    rows: list[dict[str, str]],
) -> Path:
    """Write rows to output_dir/<source>/%Y/%m/%Y%m%d.csv; return path."""
    year = partition_date.strftime("%Y")
    month = partition_date.strftime("%m")
    date_str = partition_date.strftime("%Y%m%d")
    folder = output_dir / source_system / year / month
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{date_str}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def generate(
    output_dir: Path,
    start_date: date,
    days: int,
    sources: tuple[str, ...],
    num_entities: int,
    noise_prob: float,
    seed: int | None,
    master_source: str,
    master_change_prob: float,
) -> None:
    """Generate canonical entities and emit daily CSV snapshots with noise.

    Snapshot semantics:
    - Each (date, source_system, entity_id) has at most one row.
    - The configured master source owns address changes across days:
      * On later dates, some entities get a new address in the master source.
      * Non-master sources emit at most one record per entity per date with no
        special address ownership semantics.
    """
    rng = random.Random(seed)
    fake = Faker(seed=seed) if seed is not None else Faker()

    entities = _generate_canonical_entities(num_entities, fake, rng)
    address_by_entity = {entity.entity_id: entity.address for entity in entities}

    master_source = master_source.lower()

    for day_offset in range(days):
        partition_date = start_date + timedelta(days=day_offset)
        base_dt = datetime(
            year=partition_date.year,
            month=partition_date.month,
            day=partition_date.day,
            hour=0,
            minute=0,
            second=0,
        )
        row_counter = 0

        for source_system in sources:
            source_system = source_system.lower()
            is_master = source_system == master_source

            if is_master:
                # Master source: full snapshot, all entities every day.
                chosen = entities
            else:
                # Non-master sources: overlapping subset for variety.
                sample_size = min(
                    num_entities,
                    max(1, int(num_entities * (0.4 + rng.random() * 0.5))),
                )
                chosen = rng.sample(entities, sample_size)

            rows: list[dict[str, str]] = []

            for idx, entity in enumerate(chosen):
                current_address = address_by_entity[entity.entity_id]

                if is_master and day_offset > 0 and rng.random() < master_change_prob:
                    # Simulate an address change owned by the master source on this date.
                    raw_address = fake.address()
                    current_address = " ".join(raw_address.replace("\n", " ").split())
                    address_by_entity[entity.entity_id] = current_address

                effective_entity = CanonicalEntity(
                    entity_id=entity.entity_id,
                    full_name=entity.full_name,
                    email=entity.email,
                    address=current_address,
                    phone=entity.phone,
                )
                created_at = (base_dt + timedelta(seconds=row_counter)).isoformat()
                row_counter += 1

                source_record_id = f"{source_system}_{partition_date:%Y%m%d}_{idx:06d}"

                rows.append(
                    _noisy_row(
                        effective_entity,
                        source_system,
                        source_record_id,
                        created_at,
                        noise_prob,
                        rng,
                    ),
                )

            path = _write_partitioned_csv(output_dir, partition_date, source_system, rows)
            logger.info("Wrote %s with %d rows", path, len(rows))

    logger.info(
        "Generated %d entities across %d sources over %d day(s) (master source: %s)",
        num_entities,
        len(sources),
        days,
        master_source,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate synthetic entity-resolution data to partitioned CSVs.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Base directory for partition folders (default: %(default)s)",
    )
    parser.add_argument(
        "--date",
        type=lambda s: datetime.strptime(s, "%Y%m%d").date(),
        default=date.today(),
        help="Start date YYYYMMDD (default: today)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help="Number of consecutive days to generate (default: %(default)s)",
    )
    parser.add_argument(
        "--sources",
        type=str,
        default=",".join(DEFAULT_SOURCES),
        help="Comma-separated source names (default: %(default)s)",
    )
    parser.add_argument(
        "--num-entities",
        type=int,
        default=DEFAULT_NUM_ENTITIES,
        help="Number of canonical entities to generate (default: %(default)s)",
    )
    parser.add_argument(
        "--noise",
        type=float,
        default=DEFAULT_NOISE_PROB,
        metavar="P",
        help="Probability of noise per field (default: %(default)s)",
    )
    parser.add_argument(
        "--master-source",
        type=str,
        default=DEFAULT_MASTER_SOURCE,
        help=(
            "Source system that owns addresses; may emit multiple address versions "
            "(default: %(default)s)"
        ),
    )
    parser.add_argument(
        "--master-change-prob",
        type=float,
        default=DEFAULT_MASTER_CHANGE_PROB,
        help=(
            "Daily probability that the master source changes an entity's address "
            "(default: %(default)s)"
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducibility",
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
    sources = tuple(s.strip().lower() for s in args.sources.split(",") if s.strip())
    if not sources:
        logger.error("At least one source is required")
        raise SystemExit(1)
    if args.num_entities < 1:
        logger.error("--num-entities must be >= 1")
        raise SystemExit(1)
    if not 0 <= args.noise <= 1:
        logger.error("--noise must be between 0 and 1")
        raise SystemExit(1)
    if args.days < 1:
        logger.error("--days must be >= 1")
        raise SystemExit(1)
    if not 0 <= args.master_change_prob <= 1:
        logger.error("--master-change-prob must be between 0 and 1")
        raise SystemExit(1)

    generate(
        output_dir=args.output_dir,
        start_date=args.date,
        days=args.days,
        sources=sources,
        num_entities=args.num_entities,
        noise_prob=args.noise,
        seed=args.seed,
        master_source=args.master_source.lower(),
        master_change_prob=args.master_change_prob,
    )


if __name__ == "__main__":
    main()
