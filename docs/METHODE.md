# Méthode de Fire Force

Texte de référence pour le rapport. Aucun résultat chiffré : seulement la méthode et ses limites.

## 1. Données
Détections de feux actifs NASA FIRMS (MODIS, VIIRS S-NPP, NOAA-20, NOAA-21) sur l'Afrique, agrégées par cellule de 30 km (projection équivalente, donc cellules de même surface) et par jour : nombre de détections et puissance radiative (FRP).

## 2. Harmonisation
Les capteurs n'ont pas la même résolution : un même incendie donne plus de détections avec VIIRS (375 m) qu'avec MODIS (1 km). Pour obtenir une série comparable dans le temps :
1. un capteur de **référence** fait foi tous les jours où il a observé ;
2. les jours où il manque, un capteur de **secours** le remplace, multiplié par un **facteur d'étalonnage** = somme(référence) / somme(secours) sur les jours où les deux ont observé, calculé séparément pour chaque mois du calendrier ;
3. un jour sans aucun capteur est un **trou** : il n'est jamais compté comme zéro feu et il est exclu des moyennes.

Limite : un facteur unique par mois ignore les différences régionales (zone climatique, type de végétation). La FRP de la série harmonisée n'est pas étalonnée.

## 3. Zone et période
La zone (rectangle ou polygone dessiné) retient les cellules dont le **centre** est dans la zone ; une zone plus petite qu'une cellule utilise la cellule qui la contient. La surface affichée est celle du polygone, projeté en équivalent.

## 4. Normale et anomalies
- L'année est découpée en **52 semaines** de 7 jours à partir du 1er janvier (la 52e absorbe les 8 ou 9 derniers jours). Une semaine n'est évaluée que si au moins 70 % de ses jours ont des données ; sa valeur est ramenée à 7 jours.
- La **normale** d'une semaine est la moyenne de la même semaine dans **les autres années** (l'année évaluée est exclue). Il faut au moins 4 autres années : la base couvre de janvier 2020 à août 2025, donc une semaine située après début août n'a que 4 autres années disponibles.
- Niveau **élevé** : valeur supérieure au 75ᵉ centile des autres années, au moins 1,25 fois la normale, et au moins 10 détections. Niveau **critique** : supérieure au 90ᵉ centile, au moins 1,5 fois la normale, au moins 10 détections. Les seuils sont réglables dans l'application.
- Une **période à surveiller** est un groupe de semaines **consécutives et de même niveau** : des semaines élevées côte à côte forment une période élevée, des semaines critiques côte à côte forment une période critique, et un changement de niveau ouvre une nouvelle période. Elles sont classées par niveau puis par excédent (observé moins normale).
- La **fenêtre homologue** compare le total de la période choisie aux mêmes dates de chaque autre année.

Limites : la normale et les centiles reposent sur 4 ou 5 années seulement, ce qui rend les seuils de centile approximatifs ; la normale est une moyenne sur la période disponible (pas de correction de tendance), et un seul indicateur (nombre de détections) est évalué, sans tenir compte de la météo ni de la végétation.

## 5. Confirmation entre capteurs
Chaque capteur est évalué séparément contre **son propre** historique, avec la même méthode. Une anomalie est **confirmée** quand au moins deux capteurs la signalent et que la moitié au moins des capteurs évaluables la signalent ; **isolée** quand un seul la signale ; **non vérifiable** quand moins de deux capteurs sont évaluables. Les capteurs d'une même famille (VIIRS) ne sont pas totalement indépendants : MODIS est le témoin le plus distinct.

## 6. Ce que l'application n'est pas
Elle montre où et quand des feux actifs sont détectés par satellite (feux de forêt, de savane, brûlis agricoles). Elle ne distingue pas leur origine, ne prévoit pas les feux futurs, et ne remplace pas une alerte opérationnelle.
