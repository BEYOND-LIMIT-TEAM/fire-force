"""Charger la grille et fire_daily dans Neon (ou tout PostgreSQL + PostGIS).

Pensé pour une connexion qui peut couper :
  - les données sont envoyées par paquets, chacun validé séparément ;
  - en cas de coupure, le script se reconnecte tout seul et reprend
    au premier paquet manquant ;
  - si le script s'arrête complètement, il suffit de le relancer avec
    la même commande : il reprend là où il en était.

Entrées :
    data/reference/grid_cells.parquet          (build_grid_cells.py)
    data/db/fire_daily_<début>_<fin>.parquet    (build_daily_table.py)

Connexion : variable NEON_DATABASE_URL du fichier .env, ou --dsn.

Exemples (depuis la racine du projet) :
    # Chargement (ou reprise après une coupure)
    python src/fire_pipeline/storage/load_to_neon.py \
        --daily data/db/fire_daily_2020-01-01_2025-08-03.parquet

    # Tout vider et recommencer (par exemple après avoir changé de période)
    python src/fire_pipeline/storage/load_to_neon.py --restart \
        --daily data/db/fire_daily_2020-01-01_2025-08-03.parquet
"""

import argparse
import io
import os
import time
from pathlib import Path

import psycopg
import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_FILE = PROJECT_ROOT / "sql" / "schema.sql"
CELLS_FILE = PROJECT_ROOT / "data" / "reference" / "grid_cells.parquet"

CHUNK_ROWS = 250_000        # lignes par paquet (≈ 15 Mo envoyés, validés d'un coup)
MAX_RETRIES = 8             # reconnexions successives avant d'abandonner
BYTES_PER_ROW = 83          # même valeur que build_daily_table.py
MAX_DAILY_MB = 850          # on refuse de charger au-delà (limite Neon : 1 Go)

CELL_COLUMNS = [
    "cell_id", "grid_x", "grid_y", "grid_id",
    "center_lon", "center_lat", "geom",
]
DAILY_COLUMNS = [
    "cell_id", "date",
    "modis_frp_sum", "modis_frp_max",
    "viirs_frp_sum", "viirs_frp_max",
    "modis_count", "viirs_count",
]

OLD_TABLES = ("daily_fire_grid", "daily_fire_grid_staging", "fire_grid_cells")

SENSOR_PRODUCTS = {
    "MODIS": "MODIS C6.1 (Terra + Aqua), archive FIRMS",
    "VIIRS": "VIIRS NOAA-20 (J1V-C2), archive FIRMS",
}


# ---------------------------------------------------------------------
# Connexion robuste
# ---------------------------------------------------------------------

def connect(dsn):
    # Les « keepalives » détectent vite une connexion morte au lieu
    # de rester bloqué indéfiniment.
    return psycopg.connect(
        dsn,
        connect_timeout=30,
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=5,
    )


def with_retries(dsn, label, action):
    """Exécuter action(conn) ; en cas de coupure, se reconnecter et recommencer."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with connect(dsn) as conn:
                return action(conn)
        except psycopg.OperationalError as error:
            wait = min(10 * attempt, 60)
            print(f"\nConnexion perdue pendant « {label} » "
                  f"(tentative {attempt}/{MAX_RETRIES}) : {error}")
            if attempt == MAX_RETRIES:
                raise SystemExit(
                    "Abandon. Relance la même commande quand la connexion "
                    "sera stable : le chargement reprendra où il s'est arrêté."
                )
            print(f"Nouvelle tentative dans {wait} s...")
            time.sleep(wait)


def constraint_exists(conn, name):
    return conn.execute(
        "SELECT 1 FROM pg_constraint WHERE conname = %s", (name,)
    ).fetchone() is not None


# ---------------------------------------------------------------------
# Envoi des données
# ---------------------------------------------------------------------

def to_csv(table):
    buffer = io.BytesIO()
    # Les valeurs manquantes sont écrites vides → NULL pour PostgreSQL.
    pacsv.write_csv(table, buffer, pacsv.WriteOptions(include_header=False))
    return buffer.getvalue()


def copy_rows(conn, table_name, columns, arrow_table):
    sql = (
        f"COPY public.{table_name} ({', '.join(columns)}) "
        "FROM STDIN WITH (FORMAT CSV)"
    )
    with conn.cursor() as cur, cur.copy(sql) as copy:
        copy.write(to_csv(arrow_table))


def iter_chunks(path, skip):
    """Lire le Parquet par paquets de CHUNK_ROWS lignes, en sautant les `skip` premières."""
    parquet = pq.ParquetFile(path)
    position = 0
    pending = []
    pending_rows = 0

    for batch in parquet.iter_batches(batch_size=CHUNK_ROWS):
        start, end = position, position + batch.num_rows
        position = end
        if end <= skip:
            continue
        if start < skip:
            batch = batch.slice(skip - start)

        pending.append(batch)
        pending_rows += batch.num_rows
        if pending_rows >= CHUNK_ROWS:
            yield pending
            pending, pending_rows = [], 0

    if pending:
        yield pending


def row_at(path, index):
    """Renvoyer (cell_id, date) de la ligne numéro `index` du Parquet."""
    position = 0
    for batch in pq.ParquetFile(path).iter_batches(
        batch_size=CHUNK_ROWS, columns=["cell_id", "date"]
    ):
        if index < position + batch.num_rows:
            row = batch.slice(index - position, 1).to_pylist()[0]
            return row["cell_id"], row["date"]
        position += batch.num_rows
    return None


# ---------------------------------------------------------------------
# Étapes
# ---------------------------------------------------------------------

def warn_old_tables(conn):
    rows = conn.execute("""
        SELECT c.relname, pg_total_relation_size(c.oid)
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relname = ANY(%s)
    """, (list(OLD_TABLES),)).fetchall()

    if rows:
        print("\nATTENTION : les anciennes tables existent encore :")
        for name, size in rows:
            print(f"  {name} : {size / 1e6:.0f} Mo")
        print("Supprime-les avant de charger (sql/drop_old_tables.sql).\n")
    return sum(size for _, size in rows)


def prepare(conn, restart, estimated_mb):
    old_size = warn_old_tables(conn)
    if old_size / 1e6 + estimated_mb > MAX_DAILY_MB:
        raise SystemExit("Anciennes tables + nouvelles données : quota dépassé.")

    print("Application du schéma...")
    conn.execute(SCHEMA_FILE.read_text(encoding="utf-8"))
    conn.commit()

    # Sans clé primaire ni clé étrangère pendant l'envoi : c'est bien plus
    # rapide, et l'index reconstruit à la fin est plus compact.
    for name in ("fire_daily_cell_fkey", "fire_daily_pkey"):
        if constraint_exists(conn, name):
            conn.execute(f"ALTER TABLE public.fire_daily DROP CONSTRAINT {name}")
    conn.commit()

    already = conn.execute("SELECT COUNT(*) FROM public.fire_daily").fetchone()[0]

    # On vide si on le demande, ou si la table est vide : un envoi
    # interrompu laisse des lignes « mortes » qui occupent de la place,
    # et TRUNCATE les libère vraiment.
    if restart or already == 0:
        print("Vidage des tables...")
        conn.execute(
            "TRUNCATE public.fire_daily, public.grid_cells, public.sensor_coverage"
        )
        conn.commit()


def load_cells(conn):
    expected = pq.ParquetFile(CELLS_FILE).metadata.num_rows
    present = conn.execute("SELECT COUNT(*) FROM public.grid_cells").fetchone()[0]

    if present == expected:
        print(f"Grille déjà chargée ({present:,} cellules).")
        return present

    print("\nChargement de la grille...")
    conn.execute("TRUNCATE public.grid_cells")
    copy_rows(conn, "grid_cells", CELL_COLUMNS, pq.read_table(CELLS_FILE))
    conn.commit()
    print(f"  grid_cells : {expected:,} cellules")
    return expected


def resume_point(conn, daily_file, total):
    """Nombre de lignes déjà en base, après vérification qu'elles correspondent au fichier."""
    done = conn.execute("SELECT COUNT(*) FROM public.fire_daily").fetchone()[0]
    if done == 0:
        return 0

    if done > total:
        raise SystemExit(
            f"La base contient {done:,} lignes mais le fichier seulement {total:,}. "
            "Ce n'est pas le même fichier : relance avec --restart."
        )

    # Les paquets sont validés entiers et le fichier est trié : la dernière
    # ligne en base doit être la ligne numéro done-1 du fichier.
    in_db = conn.execute("""
        SELECT cell_id, date FROM public.fire_daily
        ORDER BY cell_id DESC, date DESC LIMIT 1
    """).fetchone()
    in_file = row_at(daily_file, done - 1)
    if tuple(in_db) != tuple(in_file):
        raise SystemExit(
            "Les lignes déjà en base ne correspondent pas à ce fichier. "
            "Relance avec --restart."
        )
    return done


def load_daily(dsn, daily_file):
    total = pq.ParquetFile(daily_file).metadata.num_rows
    attempts = 0

    while True:
        try:
            with connect(dsn) as conn:
                done = resume_point(conn, daily_file, total)
                if done == total:
                    print(f"fire_daily complète ({total:,} lignes).")
                    return total
                if done:
                    print(f"\nReprise à la ligne {done:,} / {total:,}")
                else:
                    print("\nChargement de fire_daily...")

                started = time.time()
                sent_now = 0
                for chunk in iter_chunks(daily_file, skip=done):
                    rows = sum(batch.num_rows for batch in chunk)
                    copy_rows(conn, "fire_daily", DAILY_COLUMNS,
                              pa.Table.from_batches(chunk))
                    conn.commit()          # ce paquet est définitivement enregistré
                    attempts = 0
                    done += rows
                    sent_now += rows

                    rate = sent_now / max(time.time() - started, 1)
                    remaining = (total - done) / rate / 60
                    print(f"  fire_daily : {done:,} / {total:,} "
                          f"({100 * done / total:.0f} %, "
                          f"reste ≈ {remaining:.0f} min)", flush=True)
                return total

        except psycopg.OperationalError as error:
            attempts += 1
            wait = min(10 * attempts, 60)
            print(f"\nConnexion perdue (tentative {attempts}/{MAX_RETRIES}) : {error}")
            if attempts >= MAX_RETRIES:
                raise SystemExit(
                    "Abandon. Relance la même commande quand la connexion sera "
                    "stable : le chargement reprendra où il s'est arrêté."
                )
            print(f"Reconnexion dans {wait} s (le dernier paquet incomplet sera renvoyé)...")
            time.sleep(wait)


def finalize(conn):
    if not constraint_exists(conn, "fire_daily_pkey"):
        print("\nReconstruction de la clé primaire (quelques minutes, sans affichage)...")
        # Échoue s'il y a un doublon : c'est voulu, c'est notre dernier contrôle.
        conn.execute("""
            ALTER TABLE public.fire_daily
            ADD CONSTRAINT fire_daily_pkey PRIMARY KEY (cell_id, date)
        """)
        conn.commit()

    if not constraint_exists(conn, "fire_daily_cell_fkey"):
        print("Vérification du lien avec la grille...")
        conn.execute("""
            ALTER TABLE public.fire_daily
            ADD CONSTRAINT fire_daily_cell_fkey FOREIGN KEY (cell_id)
            REFERENCES public.grid_cells (cell_id)
        """)
        conn.commit()

    conn.execute("DELETE FROM public.sensor_coverage")
    for sensor, column in (("MODIS", "modis_count"), ("VIIRS", "viirs_count")):
        conn.execute(f"""
            INSERT INTO public.sensor_coverage (sensor, product, start_date, end_date)
            SELECT %s, %s, MIN(date), MAX(date)
            FROM public.fire_daily
            WHERE {column} IS NOT NULL
            HAVING COUNT(*) > 0
        """, (sensor, SENSOR_PRODUCTS[sensor]))
    conn.commit()

    conn.execute("ANALYZE public.grid_cells")
    conn.execute("ANALYZE public.fire_daily")
    conn.commit()


def report(conn, cells, daily):
    coverage = conn.execute(
        "SELECT sensor, start_date, end_date FROM public.sensor_coverage ORDER BY sensor"
    ).fetchall()

    print("\nCHARGEMENT TERMINÉ")
    print(f"Cellules : {cells:,}")
    print(f"Cellule-jours : {daily:,}")
    for sensor, first, last in coverage:
        print(f"  {sensor} : {first} → {last}")

    print("\nTaille dans la base :")
    for table in ("grid_cells", "fire_daily", "sensor_coverage"):
        size = conn.execute(
            "SELECT pg_total_relation_size(%s)", (f"public.{table}",)
        ).fetchone()[0]
        print(f"  {table:<16}{size / 1e6:>8.1f} Mo")
    total = conn.execute("SELECT pg_database_size(current_database())").fetchone()[0]
    print(f"  {'base entière':<16}{total / 1e6:>8.1f} Mo  (limite Neon gratuite : 1 000 Mo)")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--daily", required=True, type=Path,
                        help="Parquet produit par build_daily_table.py")
    parser.add_argument("--dsn", help="Chaîne de connexion (sinon NEON_DATABASE_URL)")
    parser.add_argument("--restart", action="store_true",
                        help="Tout vider et recommencer depuis le début.")
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")
    dsn = args.dsn or os.getenv("NEON_DATABASE_URL")
    if not dsn:
        raise SystemExit("ERREUR : NEON_DATABASE_URL est absent du fichier .env.")

    daily_file = args.daily if args.daily.is_absolute() else PROJECT_ROOT / args.daily
    for path in (SCHEMA_FILE, CELLS_FILE, daily_file):
        if not path.is_file():
            raise SystemExit(f"Fichier introuvable : {path}")

    parquet = pq.ParquetFile(daily_file)
    if parquet.schema_arrow.names != DAILY_COLUMNS:
        raise SystemExit(f"Colonnes inattendues : {parquet.schema_arrow.names}")

    daily_rows = parquet.metadata.num_rows
    estimated_mb = daily_rows * BYTES_PER_ROW / 1e6
    print(f"fire_daily : {daily_rows:,} lignes ≈ {estimated_mb:.0f} Mo estimés")
    if estimated_mb > MAX_DAILY_MB:
        raise SystemExit(
            f"Trop gros pour Neon gratuit (> {MAX_DAILY_MB} Mo). "
            "Réduis la période avec build_daily_table.py --start/--end."
        )

    with_retries(dsn, "préparation",
                 lambda conn: prepare(conn, args.restart, estimated_mb))
    cells = with_retries(dsn, "grille", load_cells)
    daily = load_daily(dsn, daily_file)
    with_retries(dsn, "finalisation", finalize)
    with_retries(dsn, "bilan", lambda conn: report(conn, cells, daily))


if __name__ == "__main__":
    main()
