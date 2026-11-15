-- =====================================================================
-- Suppression des ANCIENNES tables (premier schéma)
--
-- À lancer UNE FOIS sur Neon, après avoir vérifié que plus personne
-- ne les utilise. Elles occupent de la place dans la limite de 1 Go
-- et sont remplacées par grid_cells / fire_daily (voir schema.sql).
--
--   psql "$NEON_DATABASE_URL" -f sql/drop_old_tables.sql
-- =====================================================================

DROP TABLE IF EXISTS public.daily_fire_grid_staging;
DROP TABLE IF EXISTS public.daily_fire_grid;
DROP TABLE IF EXISTS public.fire_grid_cells;
