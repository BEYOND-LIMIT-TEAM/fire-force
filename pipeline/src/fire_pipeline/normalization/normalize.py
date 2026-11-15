import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


PROJECT_ROOT = Path(__file__).resolve().parents[3]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
REJECTED_DIR = PROJECT_ROOT / "data" / "rejected"

CHUNK_SIZE = 250_000

COLUMN_MAPPING = {
    "latitude": "latitude",
    "longitude": "longitude",
    "brightness": "brightness",
    "scan": "scan",
    "track": "track",
    "acq_date": "acquisition_date",
    "acq_time": "acquisition_time",
    "satellite": "satellite",
    "instrument": "instrument",
    "confidence": "confidence",
    "version": "product_version",
    "bright_t31": "brightness_t31",
    "frp": "frp",
    "daynight": "daynight",
    "type": "detection_type",
}

FLOAT_COLUMNS = {
    "latitude", "longitude", "brightness", "scan",
    "track", "brightness_t31", "frp",
}

INTEGER_COLUMNS = {"confidence", "detection_type"}

SCHEMA = pa.schema([
    ("latitude", pa.float64()),
    ("longitude", pa.float64()),
    ("brightness", pa.float64()),
    ("scan", pa.float64()),
    ("track", pa.float64()),
    ("acquisition_date", pa.string()),
    ("acquisition_time", pa.string()),
    ("satellite", pa.string()),
    ("instrument", pa.string()),
    ("confidence", pa.int64()),
    ("product_version", pa.string()),
    ("brightness_t31", pa.float64()),
    ("frp", pa.float64()),
    ("daynight", pa.string()),
    ("detection_type", pa.int64()),
    ("source_file", pa.string()),
])


def convert_value(column, value):
    value = value.strip()

    if not value:
        return None

    if column == "acquisition_date":
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()

    if column == "acquisition_time":
        if not value.isdigit() or len(value) > 4:
            raise ValueError(f"Heure invalide : {value}")
        value = value.zfill(4)
        hour, minute = int(value[:2]), int(value[2:])
        if hour > 23 or minute > 59:
            raise ValueError(f"Heure invalide : {value}")
        return f"{hour:02d}:{minute:02d}"

    if column in FLOAT_COLUMNS:
        return float(value)

    if column in INTEGER_COLUMNS:
        return int(value)

    return value


def process_file(source_path, limit=None):
    suffix = "_sample" if limit else ""
    output_path = PROCESSED_DIR / f"{source_path.stem}{suffix}.parquet"
    temporary_path = output_path.with_suffix(".parquet.tmp")
    rejected_path = REJECTED_DIR / f"{source_path.stem}.normalization_rejected.jsonl"

    total_rows = 0
    rejected_rows = 0
    processed_records = 0
    writer = None

    try:
        with source_path.open("r", encoding="utf-8-sig", newline="") as source, \
             rejected_path.open("w", encoding="utf-8") as rejected_file:

            reader = csv.reader(source, strict=True)
            header = next(reader, None)

            if not header:
                raise ValueError("En-tête CSV absent.")

            missing = set(COLUMN_MAPPING) - set(header)
            if missing:
                raise ValueError(f"Colonnes absentes : {sorted(missing)}")

            batch = []

            for record_number, values in enumerate(reader, start=2):
                if limit is not None and processed_records >= limit:
                    break
                processed_records += 1

                if len(values) != len(header):
                    error = (
                        f"Nombre de champs incorrect : "
                        f"{len(values)} au lieu de {len(header)}"
                    )
                    rejected_file.write(json.dumps({
                        "record_number": record_number,
                        "error": error,
                        "data": values,
                    }, ensure_ascii=False) + "\n")
                    rejected_rows += 1
                    continue

                row = dict(zip(header, values))

                try:
                    normalized = {
                        target: convert_value(target, row[source])
                        for source, target in COLUMN_MAPPING.items()
                    }
                    normalized["source_file"] = source_path.name
                    batch.append(normalized)

                except (ValueError, TypeError, OverflowError) as error:
                    rejected_file.write(json.dumps({
                        "record_number": record_number,
                        "error": str(error),
                        "data": values,
                    }, ensure_ascii=False) + "\n")
                    rejected_rows += 1
                    continue

                if len(batch) >= CHUNK_SIZE:
                    table = pa.Table.from_pylist(batch, schema=SCHEMA)
                    if writer is None:
                        writer = pq.ParquetWriter(
                            temporary_path, SCHEMA, compression="zstd"
                        )
                    writer.write_table(table)
                    total_rows += len(batch)
                    batch.clear()
                    print(f"  {total_rows:,} observations normalisées")

            if batch:
                table = pa.Table.from_pylist(batch, schema=SCHEMA)
                if writer is None:
                    writer = pq.ParquetWriter(
                        temporary_path, SCHEMA, compression="zstd"
                    )
                writer.write_table(table)
                total_rows += len(batch)

        if writer is None:
            raise ValueError("Aucune observation valide à normaliser.")

        writer.close()
        writer = None
        temporary_path.replace(output_path)

        print("\nNormalisation terminée.")
        print(f"Fichier : {output_path}")
        print(f"Observations normalisées : {total_rows:,}")
        print(f"Lignes rejetées : {rejected_rows:,}")
        if rejected_rows:
            print(f"Détails des rejets : {rejected_path}")

    except Exception:
        if writer is not None:
            writer.close()
        temporary_path.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--limit", type=int,
        help="Nombre maximum de lignes à tester (crée un fichier _sample)."
    )
    args = parser.parse_args()

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    REJECTED_DIR.mkdir(parents=True, exist_ok=True)

    source_path = RAW_DIR / "fire_archive_M-C61_847830.csv"
    if not source_path.is_file():
        raise SystemExit(f"Fichier introuvable : {source_path}")

    process_file(source_path, limit=args.limit)


if __name__ == "__main__":
    main()
