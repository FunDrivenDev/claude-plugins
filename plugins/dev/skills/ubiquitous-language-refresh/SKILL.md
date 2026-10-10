---
name: ubiquitous-language-refresh
description: Rescan a codebase against its existing ubiquitous-language glossary and report what changed — new terms, renamed or drifted meanings, terms that have vanished, and code that now contradicts a human-written definition. Use whenever a glossary already exists and the user wants to refresh, update, re-scan, diff or check it, mentions new vocabulary appearing, terms disappearing, or asks whether the glossary is still accurate. If no glossary exists yet, use ubiquitous-language-discover instead.
---

# Ubiquitous Language — Refresh

Rescan a codebase whose glossary already exists. The glossary is the **reference**; the scan
is evidence measured against it. Produce a diff first, then a merged file.

Le glossaire du projet est `LANGUAGE.md`, **à la racine du repo scanné**. Absent là comme
dans le state file → stop, et utiliser **ubiquitous-language-discover**. Un ancien
`docs/UBIQUITOUS-LANGUAGE.md` trouvé en place se traite comme le glossaire à fusionner :
écrire le résultat dans `LANGUAGE.md`, signaler l'ancien fichier dans le rapport et laisser
à l'équipe le soin de le supprimer.

L'index inter-projets suit la même règle de destination que Discover : repo dont le remote
`origin` nomme l'organisation `Guest-Suite` → `docs/architecture/language/index.md`
(termes transverses) et `collisions.md` (un mot, deux sens) dans le monorepo
`guest-environment` ; sinon `$HOME/Notes/UBIQUITOUS-LANGUAGE.md`, qui reste le repli quand
le checkout `guest-environment` est introuvable — le dire alors dans le rapport.

## Le glossaire fait autorité

Once a human has edited the glossary — answering an open question, correcting a definition,
confirming a translation — that content outranks anything a scan infers.

- An entry **not** marked `_déduit du nommage — non vérifié_` is human-owned. **Never rewrite
  its definition.** If the code contradicts it, add an open question and leave the entry
  intact. A rescan that quietly reverts a teammate's answer destroys the trust that makes
  the file worth maintaining.
- Entries still marked unverified may be freely improved.
- **Never delete a term.** Absence from one scan is weak evidence — the unit may have been
  skipped, renamed, or missed by the search patterns.
- Preserve any sections or free-form notes the user added. **Merge into the file; never
  regenerate it.**

## Bilingue FR/EN

Definitions, conflicts and open questions stay in French. Pair FR and EN names; never invent
a missing half — write `—` and raise a question. Un terme anglais employé tel quel à l'oral
français prend le titre `### <EN> / <EN>` et la note `- _employé tel quel en français_` :
c'est un constat d'usage, pas un `—`. Franglais identifiers
(`getFactureById`) are findings. Accents are stripped in code: search both forms,
`rg -i 'r[eé]glement'`. Watch false friends: `commande`=order, `délai`=deadline,
`demande`=request, `contrôle`=inspection, `avis`=notice/opinion/review.

## Arbitrage — le glossaire de domaine fait foi

Avant de trancher un identifiant (quel nom retenir, quel sens l'emporte), lire
`docs/domain/<context>/glossary.md` dans le repo scanné — `<context>` étant le contexte de
l'unité où le terme apparaît.

- Ce qui y est **tranché** est repris tel quel, sans reformulation, avec le renvoi
  `- **Tranché par :** docs/domain/<context>/glossary.md`. Un tel renvoi vaut entrée
  humaine : le rescan ne réécrit pas sa définition.
- Une entrée marquée `Arbitration open — do not apply yet` **reste ouverte** : la reporter
  en question ouverte, ne pas appliquer le nom proposé. Ce skill n'arbitre jamais.
- Pas de `glossary.md` pour ce contexte → le terme suit le régime ordinaire : question
  ouverte plutôt que décision.

## Budget — scan less than Discover

Past ~150k tokens the session degrades. Stay a coordinator: **never open source files in the
main session**, delegate everything, consume reports capped at ~80 lines.

- If `last_commit` is set and this is a git checkout, run
  `git diff --name-only <last_commit>..HEAD` and scan changed units first, in full.
- **Unchanged units still need a pass** to detect disappearance — but a cheap one: grep for
  known identifiers only, no fresh discovery.
- At ~120k used: stop, write state + partial diff, list remaining units for a fresh session.

## Workflow

1. **Orient** — read the state file, `LANGUAGE.md` and the cross-project index of the
   destination resolved above. Note which entries are human-owned. Resume `units_pending`
   first.
2. **Triage** — split units into *changed* (full scan) and *unchanged* (presence check) using
   the git diff; without git, treat all as changed but cap the run.
3. **Delegate** — subagents in parallel, one unit each, with the brief below. Always pass the
   known-terms list.
4. **Merge** — deduplicate, pair FR/EN, cluster synonyms, flag cross-unit conflicts, drop
   framework vocabulary. New terms follow the same bar: business concepts only, nothing a
   product manager wouldn't recognise.
5. **Resolve** — only for genuinely ambiguous terms: consulter d'abord
   `docs/domain/<context>/glossary.md` (voir Arbitrage), puis, s'il ne tranche pas, a
   subagent reads the type/aggregate definition, and the implementation if needed,
   returning one sentence.
6. **Classify** — every term into the diff table below.
7. **Write** — merged `LANGUAGE.md`, cross-project index, state file (`last_scan`, `last_commit`,
   `terms_seen`, `unseen_streak`), and a new row in `## Journal des scans`.
8. **Report** — the diff, then anything where code now contradicts a human-written entry.
   Those contradictions are the highest-value output of a refresh; lead with them.

## Classement du diff

| Classe | Signification | Action |
|---|---|---|
| **Nouveau** | absent from glossary | add entry, marked unverified |
| **Confirmé** | found, meaning matches | refresh `terms_seen`, clear unseen streak |
| **Modifié** | renamed, new variant, or meaning moved | unverified → update; human-owned → open question |
| **Non vu** | in glossary, absent from a unit actually scanned | increment `unseen_streak`, annotate entry |

Annotate a Non vu entry with `- _non vu depuis le scan du <date>_` rather than touching its
definition.

## Obsolescence

A term unseen in **3 consecutive full scans** moves to `## Termes obsolètes` with its
last-seen date — still readable, out of the way, never deleted. Announce it in the report;
never shelve a term silently. A presence-check pass on an unchanged unit counts as a scan
only if the term's identifiers were actually grepped there.

## Brief subagent

Dispatch verbatim, substituting path, known terms, and mode.

```
Scan <path>. MODE: full | presence-check.

KNOWN TERMS — report each as SEEN, NOT_FOUND, or CHANGED (+ what changed):
<comma-separated list>

If MODE is presence-check, stop after the KNOWN block — no new-term discovery.

If MODE is full, also find DOMAIN vocabulary not in the known list. Skip
framework terms (Repository, Service, Handler, DTO, Controller, Factory,
Middleware). Priority: i18n files (fr + en), migrations/entities/enums, test
names, events and routes, type definitions, docstrings.

This codebase mixes French and English. Record names exactly as written,
including franglais. Accents are stripped in code — search both forms:
rg -i 'r[eé]glement'.

Return ONLY this, max 80 lines, no file contents, max 25 new terms:

KNOWN: <term: SEEN | NOT_FOUND | CHANGED — what changed>

TERM_CODE: <identifier as written>
FR: <French business word, or ->
EN: <English business word, or ->
MEANING: <one sentence IN FRENCH, plain language>
EVIDENCE: <symbol or filename — not a code block>
CONFIDENCE: high | inferred-from-naming
VARIANTS: <other names for the same thing here, or ->

Then:
FALSE_FRIENDS: <French terms an English reader would misread, with the trap>
AMBIGUOUS: <terms you could not settle + the one question that would>
```

## Écriture

Keep the existing file structure; add entries alphabetically by French term, heading
`<FR> / <EN>`, `—` for a missing counterpart. Entry bullets, all optional:

```markdown
### Facture / Invoice
<Une phrase en français.>
- **Code :** `Invoice`, `invoice_lines`, `getFactureById()`
- **Aussi appelé :** `note` (billing), `legacyBill` (db)
- **Conflit :** dans `auth` signifie <x> ; dans `billing` signifie <y>
- **Faux ami :** `commande` = order, pas command
- **À demander à l'équipe :** <question précise>
- **Tranché par :** docs/domain/<context>/glossary.md
- _déduit du nommage — non vérifié_
- _employé tel quel en français_
- _non vu depuis le scan du <date>_
```

Append these sections if absent:

```markdown
## Termes obsolètes
| Terme | Sens | Vu pour la dernière fois |

## Journal des scans
| Date | Unités | +Nouveaux | ~Modifiés | ?Non vus |
```

Dans l'index inter-projets, ajouter le projet à la ligne d'un terme existant plutôt que de
la dupliquer ; si les sens diffèrent, ajouter une ligne aux `## Conflits inter-projets`
plutôt qu'écraser le sens en place — section qui vit dans `collisions.md` côté Guest Suite,
dans le fichier unique ailleurs. Mettre à jour les colonnes `Dernier scan` et `Termes`. En
Guest Suite, un terme n'entre dans `index.md` qu'une fois employé par au moins deux repos ;
tant qu'il n'est vu que dans un seul, il reste dans son `LANGUAGE.md`.

## Règles

- **Human edits win.** See above — this is the rule that makes refresh safe to run.
- **Never invent a definition or a translation.** Unclear → Questions ouvertes.
- **Report conflicts and drift, don't resolve them** — naming is a team decision.
- **Never commit, push or open a PR.** Write files and tell the user.
- **Cap ~25 new terms per unit**; cut the weakest rather than raising the cap.
