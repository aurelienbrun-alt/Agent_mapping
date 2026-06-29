# Calibration de l'agent de mapping — modifications à réaliser

## Contexte

Comparé au mapping de référence des consultants (218 exigences Cyfun belge → NIS2 FR),
l'agent présente deux défauts mesurés :

1. **Amplitude écrasée** : les niveaux de couverture ne sortent jamais de 25/50/75.
   L'agent ne produit **jamais 0% (Not covered)** ni **100% (Fully covered)**, alors que
   les consultants utilisent toute l'échelle (55 Covered / 66 Partial / 95 Not covered).
   Exemple : `GV.OC-01.1` est jugé "Covered" par les consultants (cible PSSI.b) mais
   plafonné à 50% par l'agent.

2. **Instabilité entre runs** : la même exigence matche des cibles différentes selon le run
   (PSSI.b, puis RISQUES.a, puis CLOISONNEMENT.d). L'atomisation est identique d'un cache
   à l'autre — la variation vient du juge LLM (température > 0) et de la sélection composite.

Objectif : **restaurer l'amplitude 0→100** et **stabiliser** les résultats.
Toutes les modifications sont dans `.env` (aucun changement de code requis).

---

## 1. Modifications dans `.env`

| Paramètre | Valeur actuelle | Nouvelle valeur | Raison |
|---|---|---|---|
| `AZURE_OPENAI_TEMPERATURE` | `0.1` | `0` | Rend le juge déterministe → supprime la dérive de cibles entre runs. |
| `OBJECT_ACTION_GATE_MODE` | `score_cap` | `off` | **Cause n°1 du « jamais 100% ».** Le gate plafonne la couverture à 50% dès que l'objet source ≠ objet cible (cf. `matching.py:_object_action_max_coverage`). En `off`, le score du juge LLM s'applique tel quel. |
| `ENABLE_OBVIOUS_GAP_SHORTCUT` | `false` | `true` | Active la détection des non-couvertures évidentes avant le LLM → permet enfin des vrais 0%. |
| `GLOBAL_FALLBACK_TOP_K` | `8` | `3` | Réduit le repêchage de candidats « de secours » qui force des matchs parasites (surtout domaines Detect/Respond). |

### Optionnel (à tester séparément)
| Paramètre | Actuel | Test | Effet |
|---|---|---|---|
| `ENABLE_CANDIDATE_RESCUE` | `true` | `false` | Cesse de repêcher des candidats faibles en partial/indirect → davantage de 0%. À mesurer : risque de manquer de vrais matchs. |

---

## 2. Modification du prompt `PROMPT_PAIRWISE_MATCH` (dans `.env`)

Le prompt actuel cherche systématiquement un gap résiduel, ce qui empêche d'atteindre 90–100.
Ajouter une **règle prioritaire** au début de la section de scoring.

**Texte à insérer** (le prompt est en anglais et tient sur une seule ligne dans `.env`,
utiliser `\n` pour les sauts de ligne) :

```
PRIORITY RULE (overrides any verbosity/gap-seeking bias): If the target addresses the same obligation and the same security objective as the source, assign 90-100 even when wording, legal drafting style, or minor implementation details differ. Only deduct below 80 when a MATERIAL element (actor, action, object, or scope) is verifiably ABSENT from the target. Never cap coverage merely because the main object is phrased differently (e.g., "mission" vs "governance policy") when the underlying obligation is addressed.
```

**Important** : conserver le prompt sur une seule ligne, encadré par des guillemets,
comme les autres `PROMPT_*` du fichier.

### Optionnel — réduire les matchs composites parasites
Dans le même prompt, la phrase *« you may select up to 3 target candidates »* peut être
ramenée à **2**, et préciser : *« only combine targets that each cover a distinct material
element of the source; do not add a target that merely shares vocabulary »*.
(C'est ce qui a fait ajouter CLOISONNEMENT.d à tort sur GV.OC-01.1.)

---

## 3. ÉTAPE OBLIGATOIRE — vider les caches de décision

⚠️ **Sans cette étape, certains changements n'auront AUCUN effet.**

Le cache des décisions LLM (`mapping_cache.py`) inclut le gate et le hash du prompt dans sa
clé → les changer invalide automatiquement le cache. **MAIS la température n'est PAS dans la
clé** → les anciennes décisions seraient réutilisées telles quelles.

Avant le re-run, **supprimer les 3 caches de décision** :

```bash
docs/cache/mapping_decisions_cache.jsonl
docs/cache/parent_gap_synthesis/parent_gap_synthesis_cache.jsonl
docs/cache/action_plan/action_plan_cache.jsonl
```

**NE PAS supprimer** les caches d'atomisation (`atomic_requirements*.json`,
`atomized_requirements.json`, embeddings) : ils sont coûteux à reconstruire (LLM + embeddings)
et n'ont pas besoin de l'être pour une recalibration. Laisser `REBUILD_CACHE=false`.

---

## 4. Protocole de test (un seul changement à la fois)

Changer **un levier à la fois** pour isoler son effet. Après chaque changement :
vider les 3 caches → relancer `python run_agent.py` → comparer aux consultants.

1. `AZURE_OPENAI_TEMPERATURE=0` → vérifier que **2 runs identiques** donnent le même résultat.
2. `OBJECT_ACTION_GATE_MODE=off` → vérifier que `GV.OC-01.1` **dépasse 50%** (idéalement Fully covered).
3. Insérer la **règle prioritaire** dans le prompt → vérifier l'apparition de **75% et 100%**.
4. `ENABLE_OBVIOUS_GAP_SHORTCUT=true` + `GLOBAL_FALLBACK_TOP_K=3` → vérifier l'apparition de **0%**.
5. (option) `ENABLE_CANDIDATE_RESCUE=false` → mesurer l'effet sur les 0%.

---

## 5. Critères d'acceptation

- [ ] Deux runs consécutifs (sans changement) produisent un résultat **identique** (stabilité).
- [ ] La distribution des niveaux contient **des 0% ET des 100%** (plus seulement 25/50/75).
- [ ] `GV.OC-01.1` ressort en **Fully covered** (aligné avec le verdict consultant).
- [ ] L'accord exact avec le mapping consultant **augmente** (référence actuelle : 31%).
- [ ] Le nombre de « Not covered » de l'agent **se rapproche** des 95 des consultants
      (actuellement 0).

---

## Référence des fichiers concernés

- `.env` — tous les paramètres et prompts ci-dessus.
- `src/matching.py:1122` — `_object_action_max_coverage()` (logique du gate, pour info).
- `src/mapping_cache.py:100` — clé du cache de décision (température absente, d'où l'étape 3).
