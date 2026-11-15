import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
REJECTED_DIR = PROJECT_ROOT / "data" / "rejected"

VALIDATOR_VERSION = 2
csv.field_size_limit(sys.maxsize)


def calculate_sha256(path):
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def validate_csv(path):
    """Valider les lignes sans imposer de schéma propre à un capteur."""

    rejected_path = REJECTED_DIR / f"{path.stem}.rejected.jsonl"
    REJECTED_DIR.mkdir(parents=True, exist_ok=True)

    accepted = 0
    rejected = 0

    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.reader(file, strict=True)
        header = next(reader, None)

        if not header:
            raise ValueError("Fichier vide ou en-tête absent.")

        if len(header) != len(set(header)):
            raise ValueError("L'en-tête contient des champs dupliqués.")

        with rejected_path.open("w", encoding="utf-8") as rejected_file:
            for record_number, row in enumerate(reader, start=2):
                if len(row) != len(header):
                    rejected += 1

                    rejected_file.write(json.dumps({
                        "record_number": record_number,
                        "expected_fields": len(header),
                        "actual_fields": len(row),
                        "data": row,
                    }, ensure_ascii=False) + "\n")
                else:
                    accepted += 1

    if rejected == 0:
        rejected_path.unlink(missing_ok=True)

    if accepted == 0:
        raise ValueError("Aucune observation valide.")

    return len(header), accepted, rejected, rejected_path


def process_file(path):
    manifest_path = path.with_suffix(".manifest.json")
    checksum = calculate_sha256(path)

    if manifest_path.exists():
        try:
            previous = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )

            if (
                previous.get("sha256") == checksum
                and previous.get("validator_version") == VALIDATOR_VERSION
            ):
                print(f"DEJA VALIDE : {path.name}")
                return

        except (json.JSONDecodeError, OSError):
            pass

    manifest = {
        "file_name": path.name,
        "file_size_bytes": path.stat().st_size,
        "sha256": checksum,
        "validated_at_utc": datetime.now(timezone.utc).isoformat(),
        "validator_version": VALIDATOR_VERSION,
    }

    try:
        columns, accepted, rejected, rejected_path = validate_csv(path)

        manifest.update({
            "columns_count": columns,
            "accepted_observations": accepted,
            "rejected_records": rejected,
            "validation_status": (
                "valid" if rejected == 0 else "valid_with_rejections"
            ),
        })

        print(f"VALIDE : {path.name}")
        print(f"  Observations acceptées : {accepted:,}")
        print(f"  Lignes rejetées : {rejected:,}")

        if rejected:
            print(f"  Détails : {rejected_path.relative_to(PROJECT_ROOT)}")

    except (ValueError, UnicodeError, csv.Error, OSError) as error:
        manifest.update({
            "validation_status": "invalid_file",
            "error": str(error),
        })

        print(f"FICHIER INVALIDE : {path.name}")
        print(f"  Motif : {error}")

    temporary_manifest = manifest_path.with_suffix(".manifest.tmp")
    temporary_manifest.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary_manifest.replace(manifest_path)


def main():
    files = sorted(RAW_DIR.glob("*.csv"))

    if not files:
        print("Aucun fichier CSV trouvé dans data/raw/.")
        return

    print(f"{len(files)} fichier(s) CSV détecté(s).\n")

    for path in files:
        process_file(path)

    print("\nValidation terminée.")


if __name__ == "__main__":
    main()
