# Patch v2.3 - Output refusionne et nettoyage du template

## Objectif

Cette version corrige deux points demandes:

1. Les onglets principaux de l'output final affichent les exigences de base/originales refusionnees, et non plus uniquement les exigences atomiques.
2. Les anciens onglets `Dashboard` et `README` du template sont supprimes/recrees pour eviter les doublons `Dashboard (2)` et `README (2)`.

## Nouveaux parametres `.env`

```env
OUTPUT_MAIN_VIEW=parent
INCLUDE_ATOMIC_DETAIL_SHEETS=true
```

- `OUTPUT_MAIN_VIEW=parent`: `Fr 1 -> Fr2` et `Fr 2 -> Fr1` affichent une ligne par exigence originale.
- `OUTPUT_MAIN_VIEW=atomic`: ancien comportement, une ligne par exigence atomique.
- `INCLUDE_ATOMIC_DETAIL_SHEETS=true`: conserve les onglets techniques atomiques.

## Nouveaux onglets

- `Fr 1 -> Fr2`: mapping refusionne au niveau exigence originale.
- `Fr 2 -> Fr1`: mapping refusionne au niveau exigence originale si bidirectionnel actif.
- `Atomic Fr 1 -> Fr2`: detail technique atomique.
- `Atomic Fr 2 -> Fr1`: detail technique atomique.
- `Parent coverage`: resume par exigence originale, score moyen, atomes couverts, gaps atomiques.

## Fichiers modifies

```text
.env
README.md
src/config.py
src/final_judge.py
src/matching.py
src/models.py
src/output_writer.py
```

## Note importante

Le cache n'a pas besoin d'etre reconstruit pour cette correction si les donnees atomiques actuelles te conviennent. Cette correction concerne surtout l'ecriture de l'Excel final.
