# Pipeline de données (équipe données)

Ce dossier accueille le travail de l'équipe données : téléchargement NASA FIRMS (MODIS, VIIRS),
nettoyage, agrégation sur la grille de 30 km, puis chargement dans Neon (PostgreSQL + PostGIS).

Sortie du pipeline : les tables `grid_cells` et `fire_daily` sur Neon, ou les parquet agrégés par capteur.
Suite de la chaîne : `data/export_neon.py` (ou directement les parquet) puis `data/build_db.py`.

Ne jamais committer d'URL de connexion, de clé FIRMS ni de fichier `.env` : copier `.env.example` (à la racine) vers `.env`.
