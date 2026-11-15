"""
Regarde l'intérieur d'un fichier .parquet SANS le charger en entier.

Usage :  python inspecter_parquet.py fichier.parquet
Dépendance : pyarrow   (pip install pyarrow)

Affiche : le nombre de lignes, les colonnes avec leur type, les valeurs min/max de chaque
colonne (lues dans les statistiques du fichier, donc instantané) et 5 lignes d'exemple.
Envoie-moi cette sortie : elle suffit pour brancher le fichier sur la base.
"""
import sys

import pyarrow.parquet as pq


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    pf = pq.ParquetFile(sys.argv[1])
    meta = pf.metadata
    print(f"Lignes : {meta.num_rows:,}   Groupes de lignes : {meta.num_row_groups}   "
          f"Colonnes : {meta.num_columns}")
    print("\n=== Colonnes ===")
    schema = pf.schema_arrow
    for i, champ in enumerate(schema):
        mn = mx = None
        ok = True
        for g in range(meta.num_row_groups):
            st = meta.row_group(g).column(i).statistics
            if st is None or not st.has_min_max:
                ok = False
                break
            mn = st.min if mn is None else min(mn, st.min)
            mx = st.max if mx is None else max(mx, st.max)
        plage = f"{mn}  ->  {mx}" if ok and mn is not None else "(pas de statistiques)"
        print(f"{champ.name:<24} {str(champ.type):<18} {plage}")
    print("\n=== 5 premières lignes ===")
    lot = next(pf.iter_batches(batch_size=5))
    print(lot.to_pandas().to_string(index=False))
    print("\nIndique maintenant quelle colonne est : la date, la latitude, la longitude, le nombre "
          "de feux (harmonisé), et éventuellement le brut et le FRP.")


if __name__ == "__main__":
    main()
