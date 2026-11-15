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

test:
	cd backend && $(PY) -m pytest -q tests
