# make demo   : données synthétiques + base + serveur   |  make test : tests   |  make run : serveur seul
PY ?= python3
SYN = data/synth

demo-data:
	$(PY) data/make_synthetic.py --sortie $(SYN)
	$(PY) data/build_db.py --source MODIS=$(SYN)/MODIS.parquet --source VIIRS_SNPP=$(SYN)/VIIRS_SNPP.parquet \
	  --source VIIRS_N20=$(SYN)/VIIRS_N20.parquet --source VIIRS_N21=$(SYN)/VIIRS_N21.parquet \
	  --reference VIIRS_SNPP --secours VIIRS_N20 VIIRS_N21 MODIS --sortie data/fireforce.duckdb --jeu demo --remplacer

run:
	cd backend && FIREFORCE_DB=../data/fireforce.duckdb uvicorn app.main:app --reload --port 8000

demo: demo-data run

# Données réelles : Neon (tables grid_cells et fire_daily) -> parquet -> base de l'application.
# Lit NEON_DATABASE_URL (l'accès lecture seule fire_reader suffit). À lancer par UNE personne,
# puis partager data/fireforce.duckdb (pas dans Git) : chaque export consomme du transfert Neon.
neon-data:
	$(PY) data/export_neon.py --sortie neon_export
	$(PY) data/build_db.py --source VIIRS=neon_export/VIIRS.parquet --source MODIS=neon_export/MODIS.parquet \
	  --reference VIIRS --secours MODIS --cellules neon_export/cells.parquet \
	  --sortie data/fireforce.duckdb --jeu firms --remplacer

test:
	cd backend && $(PY) -m pytest -q tests
