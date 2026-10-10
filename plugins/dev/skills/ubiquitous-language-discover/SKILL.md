---
name: ubiquitous-language-discover
description: First-pass discovery of a codebase's domain vocabulary — builds a DDD ubiquitous language from scratch with French/English term pairs, definitions, synonyms, naming conflicts and open questions for the team. Use when onboarding onto an unfamiliar codebase, when no glossary exists yet, or when the user mentions vocabulary, domain language, ubiquitous language, bounded contexts, franglais naming, or wants to map the concepts in a project — even if they never say "glossary". If a glossary already exists, use ubiquitous-language-refresh instead.
---

# Ubiquitous Language — Discover

Build the first glossary of a codebase. The value is not a word list: it's catching drift —
one concept named three ways, one word meaning two things in two modules, and the gap
between the French the business speaks and the English the code is written in.

If `LANGUAGE.md` already exists at the root of the scanned repo, stop and use
**ubiquitous-language-refresh**.

## Outputs

1. `LANGUAGE.md` — glossaire du projet, **à la racine du repo scanné**. Pas sous `docs/`,
   pas d'autre nom : un seul emplacement, le même dans tous les repos.
2. L'index inter-projets — deux destinations possibles, voir la section suivante.
3. `$HOME/Notes/.ubiquitous-language/<project>.state.json` — scan memory, kept outside the
   repo so scanning never dirties the working tree:

```json
{ "project": "<name>", "glossary_path": "LANGUAGE.md",
  "last_scan": "<date>", "last_commit": "<sha or null>",
  "i18n_signal": "unknown | high | low",
  "units_covered": [], "units_pending": [],
  "terms_seen": { "Facture": "<date>" }, "unseen_streak": {} }
```

## Où va l'index inter-projets

Trancher **avant** d'écrire, à partir du remote `origin` du repo scanné
(`git -C <repo> remote get-url origin`).

- **L'URL nomme l'organisation `Guest-Suite`** → l'index vit dans le monorepo
  `guest-environment`, sous `docs/architecture/language/` :
  - `index.md` — les termes **transverses**, ceux qu'au moins deux repos Guest Suite
    emploient. Un terme propre à un seul repo reste dans son `LANGUAGE.md`.
  - `collisions.md` — un même mot, deux sens selon le repo.

  Le checkout de `guest-environment` est celui qui porte `docs/architecture/` ; pour un
  `apps/<app>`, c'est le monorepo qui le contient. Introuvable (worktree isolé, clone hors
  monorepo) → repli sur `~/Notes` ci-dessous, et le dire dans le rapport.
- **Sinon** (repo hors Guest Suite) → `$HOME/Notes/UBIQUITOUS-LANGUAGE.md`, fichier unique
  portant **tous** les termes.

## Bilingue FR/EN

- **Write every definition in French.** Definitions, conflicts and open questions are in
  French; the reader is fluent in both and expects the mix.
- **Pair both names** on each entry. **Never invent the missing half** — if the business says
  « le lead », record « le lead »; write `—` rather than manufacturing a translation, and
  raise it as an open question when the gap looks real. Normalising silently destroys the
  finding.
- **Terme anglais employé tel quel à l'oral français** — ne pas fabriquer de moitié
  française : le titre est `### <EN> / <EN>` (`### Widget / Widget`) et l'entrée porte la
  note `- _employé tel quel en français_`. C'est un constat d'usage, pas un `—` : le mot a
  bien un équivalent français que personne ne dit.
- **Franglais is a finding**: `getFactureById`, `is_livraison_active` mark the language
  boundary. Record as written.
- **Flag false friends**: `commande`=order not command, `délai`=deadline/lead time,
  `demande`=request, `contrôle`=inspection, `avis`=notice/opinion/review. Wrong assumptions
  here cause real bugs.
- **Accents are stripped in identifiers** (`reglement`, `echeance`). Search both:
  `rg -i 'r[eé]glement'`. Missing this halves recall.

## Arbitrage — le glossaire de domaine fait foi

Avant de trancher un identifiant (quel nom retenir, quel sens l'emporte), lire
`docs/domain/<context>/glossary.md` dans le repo scanné — `<context>` étant le contexte de
l'unité où le terme apparaît.

- Ce qui y est **tranché** est repris tel quel, sans reformulation, avec le renvoi
  `- **Tranché par :** docs/domain/<context>/glossary.md`.
- Une entrée marquée `Arbitration open — do not apply yet` **reste ouverte** : la reporter
  en question ouverte, ne pas appliquer le nom proposé. Ce skill n'arbitre jamais.
- Pas de `glossary.md` pour ce contexte → le terme suit le régime ordinaire : question
  ouverte plutôt que décision.

## Budget — hard rule

Past ~150k tokens the session degrades, so stay a coordinator, never a reader.

- **Never open source files in the main session.** Delegate all scanning; consume only
  reports, capped at ~80 lines each. Reject any report dumping file contents.
- At ~120k used: stop, write state + partial glossary, tell the user which units remain and
  that a fresh session resumes from the state file.
- No subagents available: scan units sequentially, writing after each so handover loses
  nothing.

## Workflow

1. **Map cheaply** — directory tree (2–3 levels), package manifests, docs index, migration
   and i18n filenames. Names only, no file bodies.
2. **Partition** — ≤15 units, one per module / package / candidate bounded context. Skip
   vendor, node_modules, build output, generated code, lockfiles.
3. **Delegate** — subagents in parallel, one unit each, using the brief below.
4. **Merge** — deduplicate, pair FR/EN, cluster synonyms, flag conflicts (same word,
   different meanings across units), drop technical vocabulary.
5. **Resolve** — only for terms still ambiguous: consulter d'abord
   `docs/domain/<context>/glossary.md` (voir Arbitrage), puis, s'il ne tranche pas, a
   subagent reads the type/aggregate definition, and its implementation if the type doesn't
   settle it, returning one sentence.
6. **Write** — `LANGUAGE.md`, l'index inter-projets de la destination retenue, state file.
7. **Report** — units covered, term count, conflicts, FR/EN gaps, open questions, and how
   useful the i18n files actually were (record the verdict in `i18n_signal`).

## Termes à retenir

Capture business concepts: entities, states and lifecycles (`brouillon`, `soldé`, `résilié`),
roles, events, business rules, units, identifiers, domain abbreviations.

Skip framework vocabulary — Repository, Service, Handler, DTO, Controller, Mapper, Factory,
Middleware. **Exception**: capture one when the codebase overloads it with domain meaning
(a `Ledger` service that is really the accounting model).

If a term would mean nothing to a product manager, it doesn't belong.

## Où se cache le vocabulaire

Ranked by expected signal. **Rank 1 is an unverified assumption** — check it this run and
demote it if wrong.

1. **i18n files** (`lang/fr/*.php`, `locales/fr.json`, `en.json`) — *hypothesis:* they map
   identifiers to the words the business says, and parallel fr/en files hand you the pairing
   directly. Thin, stale or UI-boilerplate? Say so and set `i18n_signal: "low"`.
2. **Persistence** — migrations, entities, models, table and enum names. Columns preserve
   original vocabulary long after renames; French identifiers survive here most often.
3. **Enums, value objects, state machines** — the domain's controlled vocabulary.
4. **Test names** — `it_refuses_to_settle_a_voided_invoice` states a rule in prose.
5. **Events, jobs, queues, routes** — verbs of the domain.
6. **TS `types/`, Pinia stores, composables, components** — front-end naming often diverges
   from back-end naming; that divergence *is* a finding, and French labels surface here.
7. **Docstrings, ADRs, README** — often stale; prefer code when they clash.

## Brief subagent

Dispatch verbatim, substituting the unit path.

```
Scan <path> for DOMAIN vocabulary only. Skip framework terms (Repository,
Service, Handler, DTO, Controller, Factory, Middleware).

This codebase mixes French and English. Record names exactly as written,
including franglais. Accents are stripped in code — search both forms:
rg -i 'r[eé]glement'.

Priority: i18n files (fr + en), migrations/entities/enums, test names,
events and routes, type definitions, docstrings.

Return ONLY this, max 80 lines, no file contents, max 25 terms:

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

## Format — glossaire projet

```markdown
# Ubiquitous Language — <project>

_Mis à jour le <date> · Couvre : <units> · <n> termes · <n> questions ouvertes_

## Contextes
<one line per module, in French: what it owns>

## Glossaire

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

## Questions ouvertes
<numbered, each answerable in one sentence>

## Journal des scans
| Date | Unités | +Nouveaux | ~Modifiés | ?Non vus |
```

Heading is `<FR> / <EN>` so either language finds it; `—` for a missing counterpart, and
`<EN> / <EN>` for a term the French speaks as is. Omit bullets that don't apply.
Alphabetical by French term. One sentence per definition — if it needs two, it's two terms.

## Format — index inter-projets

Hors Guest Suite, les trois sections tiennent dans le fichier unique
`~/Notes/UBIQUITOUS-LANGUAGE.md` :

```markdown
# Ubiquitous Language — index inter-projets

## Projets
| Projet | Chemin | Dernier scan | Termes |

## Termes
| FR | EN | Sens | Projets |

## Conflits inter-projets
| Terme | Signifie ici | Signifie là |
```

En Guest Suite, elles se répartissent sur les deux fichiers de
`docs/architecture/language/` : `Projets` et `Termes` (transverses uniquement) dans
`index.md`, `Conflits inter-projets` dans `collisions.md`.

## Règles

- **Never invent a definition or a translation.** No clear meaning → Questions ouvertes, not
  a plausible guess. Mark naming-only inferences unverified: a confidently wrong glossary is
  worse than a short one.
- **Report conflicts, don't resolve them** — naming is a team decision. Same for FR/EN
  inconsistency: flag, never normalise.
- **Never commit, push or open a PR.** Write files and tell the user.
- **40 solid terms beat 300 shallow ones.** Cap ~25 per unit; cut the weakest rather than
  raising the cap.
