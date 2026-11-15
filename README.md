# Fire Force

## Organisation du dépôt

| Dossier | Contenu |
|---|---|
| `pipeline/` | Équipe données : NASA FIRMS → nettoyage → grille 30 km → Neon |
| `data/` | `export_neon.py` (Neon → parquet), `build_db.py` (parquet → base de l'application) |
| `backend/` | API FastAPI : analyse, seuils, périodes critiques |
| `frontend/` | Interface web : carte, calendrier, graphiques |
| `science/` | Scripts d'exploration et de validation |
| `docs/` | Méthode et documentation |

Données : NASA FIRMS (MODIS et VIIRS). Le dépôt ne contient aucune donnée volumineuse ni aucun secret.

Application web qui harmonise les détections de feux actifs MODIS et VIIRS (NASA FIRMS) pour l'Afrique et produit, pour n'importe quelle zone et période, un **calendrier des feux actifs** avec les **périodes inhabituelles ou critiques**.

L'utilisateur dessine une zone sur la carte (ou saisit des coordonnées, ou choisit une région), choisit une période, et obtient en moins de deux secondes : un verdict en une phrase, la carte des feux, le calendrier jour par jour, la comparaison semaine par semaine à la normale, la liste des périodes à surveiller, et la vérification croisée entre capteurs.

## Lancer en 3 commandes (données de démonstration)

```bash
python3 -m venv .venv && source .venv/bin/activate      # Windows : .venv\Scripts\activate
pip install -r backend/requirements.txt -r backend/requirements-dev.txt
make demo            # génère des données synthétiques (~1 min), construit la base, lance http://localhost:8000
```

Sans `make` (Windows) : lancer à la main les deux commandes du fichier `Makefile` (cibles `demo-data` puis `run`).
Les données de démonstration sont **synthétiques** : elles servent à développer et à tester. Le bandeau « Données de démonstration » reste affiché en haut de l'application tant que la base est marquée `demo`.

## Avec les vraies données (parquet sur la grille 30 km)

```bash
python3 data/build_db.py \
  --source MODIS=modis_daily_grid_30km.parquet \
  --source VIIRS_SNPP=viirs_snpp.parquet --source VIIRS_N20=viirs_n20.parquet --source VIIRS_N21=viirs_n21.parquet \
  --reference VIIRS_SNPP --secours VIIRS_N20 VIIRS_N21 MODIS \
  --sortie data/fireforce.duckdb --jeu firms --remplacer
```

### Données de l'application : celles de Neon (méthode officielle)

Les données utilisées par l'application sont celles chargées dans Neon par le pipeline
(`pipeline/`, tables `grid_cells` et `fire_daily`, janvier 2020 → août 2025, MODIS et VIIRS NOAA-20).
Une seule personne construit la base, puis partage le fichier `data/fireforce.duckdb` (hors Git) :

```bash
export NEON_DATABASE_URL="postgresql://fire_reader:...@.../neondb?sslmode=require"
make neon-data       # export Neon -> neon_export/*.parquet -> data/fireforce.duckdb
make run
```

Détail des deux étapes :

Si les données sont sur Neon (tables `grid_cells` et `fire_daily`), on les exporte une fois en parquet, puis on construit la base :

```bash
pip install "psycopg[binary]" pyarrow
python3 data/export_neon.py --sortie neon_export        # demande l'URL (saisie masquée) ou lit NEON_DATABASE_URL
python3 data/build_db.py --source MODIS=neon_export/MODIS.parquet --source VIIRS=neon_export/VIIRS.parquet \
  --reference VIIRS --secours MODIS --cellules neon_export/cells.parquet \
  --sortie data/fireforce.duckdb --jeu firms --remplacer
```
`--cellules` reprend la géométrie des cellules stockée dans Neon, donc la carte est alignée sur la grille de l'équipe données.

- Colonnes attendues dans chaque parquet : `grid_x, grid_y, date, fire_count, frp_sum` (autres noms : options `--col-x`, `--col-y`, `--col-date`, `--col-count`, `--col-frp`).
- Un seul capteur est accepté (`--source MODIS=... --reference MODIS`). Les analyses marchent, mais la confirmation entre capteurs est alors « non vérifiable ».
- `--reference` fait foi chaque jour où il existe ; `--secours` le remplace les autres jours après étalonnage mensuel.
- Les parquet doivent utiliser **la même grille** (projection Albers Afrique, cellules de 30 km) et des dates en jour UTC.

## Architecture

```
parquet par capteur ──build_db.py──▶ fireforce.duckdb ──SQL──▶ FastAPI ──JSON──▶ interface web
                      (harmonisation)   (un seul fichier)     backend/app        frontend/
```

| Dossier | Rôle |
|---|---|
| `data/` | `build_db.py` (parquet → base harmonisée), `make_synthetic.py` (données de test) |
| `backend/app/store.py` | ouverture de la base, sélection des cellules d'une zone (rectangle ou polygone) |
| `backend/app/analytics.py` | semaines, normale, anomalies, épisodes, confirmation multi-capteurs |
| `backend/app/main.py` | API : `/api/meta`, `/api/cells`, `/api/map`, `/api/analyze`, `/api/health` (doc interactive : `/docs`) |
| `backend/tests/` | 11 tests (méthode et API) : `make test` |
| `frontend/` | interface (carte Leaflet, graphiques ECharts), bibliothèques embarquées : fonctionne sans internet, sauf le fond de carte |
| `science/` | scripts d'exploration et de validation du rôle science (rapport) |

La base est interrogée **en SQL** (DuckDB) : la zone choisie sélectionne ses cellules, puis les séries sont agrégées par la base, jamais en relisant des fichiers CSV. DuckDB est un moteur SQL embarqué : pas de serveur de base à héberger, un seul fichier à déployer.

## API en bref

`POST /api/analyze`

```json
{ "zone": {"type": "bbox", "bbox": [8.4, 1.6, 16.2, 13.1]},
  "start": "2024-08-04", "end": "2025-08-03",
  "q_eleve": 75, "q_critique": 90, "ratio_eleve": 1.25, "ratio_critique": 1.5, "plancher": 10, "min_annees": 4 }
```

Zone polygone : `{"type": "polygon", "coordinates": [[lon, lat], ...]}`. La réponse contient `kpi`, `calendar` (jour, valeur, niveau de la semaine, confirmation), `weeks`, `episodes`, `same_window`, `seasonal`, `sensors`, `current`, `cell_map`, `zone`.

## Déploiement

Un seul conteneur sert l'API et l'interface ; la base est montée en lecture seule :

```bash
docker compose up --build        # puis http://localhost:8000
```

Le fichier `data/fireforce.duckdb` doit exister avant. Pour un hébergeur sans disque persistant, copier la base dans l'image (ajouter `COPY data/fireforce.duckdb /data/` au Dockerfile). Le Dockerfile n'a pas pu être exécuté dans l'environnement où il a été écrit (pas de démon Docker) : à vérifier au premier lancement.

## Choix de méthode et limites

Voir `docs/METHODE.md`. À valider scientifiquement : le facteur d'étalonnage (un par mois, global), les seuils (centiles et multiples), la grille de 30 km et l'attribution des cellules à une zone (par leur centre).
