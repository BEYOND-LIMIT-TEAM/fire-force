-- =====================================================================
-- Fire Force — schéma de la base (PostgreSQL + PostGIS, Neon gratuit)
--
-- Ce fichier peut être relancé sans risque : il ne supprime rien et
-- ne crée que ce qui manque. Il est exécuté automatiquement par
-- src/fire_pipeline/storage/load_to_neon.py.
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS postgis;


-- ---------------------------------------------------------------------
-- 1. La grille : une ligne par cellule de 30 km × 30 km
--    (projection Albers centrée sur l'Afrique, voir daily_grid.py)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.grid_cells (
    -- Identifiant entier stable, calculé ainsi :
    --   cell_id = (grid_x + 500) * 1000 + (grid_y + 500)
    -- Il ne dépend que de la position de la cellule, donc il reste
    -- identique d'un rechargement à l'autre.
    cell_id     integer  PRIMARY KEY,
    grid_x      smallint NOT NULL,
    grid_y      smallint NOT NULL,
    grid_id     text     NOT NULL UNIQUE,   -- ex. "66_131", comme dans les Parquet
    center_lon  real     NOT NULL,          -- centre de la cellule (WGS84)
    center_lat  real     NOT NULL,
    geom        geometry(Polygon, 4326) NOT NULL,
    UNIQUE (grid_x, grid_y)
);

CREATE INDEX IF NOT EXISTS grid_cells_geom_idx
    ON public.grid_cells USING gist (geom);


-- ---------------------------------------------------------------------
-- 2. Les observations quotidiennes : une ligne par (cellule, jour)
--    où au moins un capteur a détecté un feu.
--
--    MODIS et VIIRS sont côte à côte sur la même ligne :
--      - une seule ligne par cellule et par jour, donc pas de doublon
--        possible grâce à la clé primaire ;
--      - deux fois moins de lignes qu'avec une colonne "sensor",
--        ce qui compte beaucoup avec la limite de 1 Go de Neon.
--
--    NULL = le capteur n'a rien détecté ce jour-là dans la cellule
--    (l'API remplace NULL par 0). Les périodes couvertes par chaque
--    capteur sont dans la table sensor_coverage.
--
--    frp_mean n'est pas stocké : frp_mean = frp_sum / count.
--    L'ordre des colonnes évite le remplissage (padding) en mémoire.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.fire_daily (
    cell_id        integer  NOT NULL,
    date           date     NOT NULL,
    modis_frp_sum  real,
    modis_frp_max  real,
    viirs_frp_sum  real,
    viirs_frp_max  real,
    modis_count    smallint,
    viirs_count    smallint,
    CONSTRAINT fire_daily_pkey PRIMARY KEY (cell_id, date),
    CONSTRAINT fire_daily_cell_fkey FOREIGN KEY (cell_id)
        REFERENCES public.grid_cells (cell_id)
);

-- Pas d'autre index : la clé primaire (cell_id, date) suffit pour
-- « toutes les cellules d'une zone sur une période ». Chaque index
-- en plus coûterait plusieurs centaines de Mo.


-- ---------------------------------------------------------------------
-- 3. Période réellement chargée pour chaque capteur
--    (remplie par load_to_neon.py ; utile au frontend pour savoir
--     quelles dates proposer et quand un capteur n'existait pas encore)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.sensor_coverage (
    sensor      text PRIMARY KEY,         -- 'MODIS' ou 'VIIRS'
    product     text NOT NULL,            -- produit FIRMS d'origine
    start_date  date NOT NULL,
    end_date    date NOT NULL,
    loaded_at   timestamptz NOT NULL DEFAULT now()
);


-- ---------------------------------------------------------------------
-- 4. Fonctions prêtes à l'emploi pour l'API
-- ---------------------------------------------------------------------

-- Calendrier jour par jour pour une zone.
-- Renvoie TOUS les jours de la période, y compris ceux sans feu (0).
-- La zone doit être en WGS84 (SRID 4326), par exemple :
--   ST_SetSRID(ST_GeomFromGeoJSON('{"type":"Polygon",...}'), 4326)
--   ST_MakeEnvelope(lon_min, lat_min, lon_max, lat_max, 4326)
CREATE OR REPLACE FUNCTION public.fire_calendar(
    zone        geometry,
    start_date  date,
    end_date    date
)
RETURNS TABLE (
    date           date,
    modis_count    integer,
    viirs_count    integer,
    modis_frp_sum  double precision,
    viirs_frp_sum  double precision,
    modis_frp_max  real,
    viirs_frp_max  real,
    active_cells   integer
)
LANGUAGE sql STABLE
AS $$
    WITH zone_cells AS (
        SELECT cell_id
        FROM public.grid_cells
        WHERE ST_Intersects(geom, zone)
    ),
    per_day AS (
        SELECT
            d.date,
            SUM(d.modis_count)::integer  AS modis_count,
            SUM(d.viirs_count)::integer  AS viirs_count,
            SUM(d.modis_frp_sum)         AS modis_frp_sum,
            SUM(d.viirs_frp_sum)         AS viirs_frp_sum,
            MAX(d.modis_frp_max)         AS modis_frp_max,
            MAX(d.viirs_frp_max)         AS viirs_frp_max,
            COUNT(*)::integer            AS active_cells
        FROM public.fire_daily d
        JOIN zone_cells c USING (cell_id)
        WHERE d.date BETWEEN start_date AND end_date
        GROUP BY d.date
    )
    SELECT
        days.day::date,
        COALESCE(p.modis_count, 0),
        COALESCE(p.viirs_count, 0),
        COALESCE(p.modis_frp_sum, 0),
        COALESCE(p.viirs_frp_sum, 0),
        p.modis_frp_max,
        p.viirs_frp_max,
        COALESCE(p.active_cells, 0)
    FROM generate_series(start_date, end_date, interval '1 day') AS days(day)
    LEFT JOIN per_day p ON p.date = days.day::date
    ORDER BY 1
$$;


-- Cellules en feu un jour donné dans une zone (pour colorer la carte).
CREATE OR REPLACE FUNCTION public.fire_cells_on(
    zone  geometry,
    day   date
)
RETURNS TABLE (
    cell_id        integer,
    grid_id        text,
    center_lon     real,
    center_lat     real,
    modis_count    smallint,
    viirs_count    smallint,
    modis_frp_sum  real,
    viirs_frp_sum  real
)
LANGUAGE sql STABLE
AS $$
    SELECT
        c.cell_id, c.grid_id, c.center_lon, c.center_lat,
        d.modis_count, d.viirs_count, d.modis_frp_sum, d.viirs_frp_sum
    FROM public.grid_cells c
    JOIN public.fire_daily d USING (cell_id)
    WHERE ST_Intersects(c.geom, zone)
      AND d.date = day
$$;
