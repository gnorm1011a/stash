# Tag Cleanup Audit

Date: 2026-09-28
Scope: full tag system review — 895 tags, hierarchy, redundancy, naming.

## Actions applied

### De-duplication
- Parent+child co-tag stripping: **6,750 scene-tag removals** — where a scene carried
  both a parent tag and one of its children, the parent was removed (Stash tag
  filters already include children, so the parent co-tag was pure noise).
- State-vs-act corrections: children that don't imply the parent act were
  unparented, and the wrongly-stripped parent was restored via backup diff
  (`M:\Backups\Stash\stash_20260928_103142`): **957 restorations**.

### Hierarchy fixes (act vs state)

| Tag | Change |
|---|---|
| Anal Gape | unparented from Anal Sex (anatomical state, not the act) |
| Anal Fingering (From Other), Anal Toys, Anal Fisting, Anal Stretching, Anal Orgasm, Anal Winking, Anal Squirting, Anal Hooks, Ass to Mouth | unparented from Anal Sex; ATM keeps `Blowjob` parent |
| Pussy to Mouth | unparented from Vaginal Sex (keeps `Blowjob`) |
| Cum in Mouth | unparented from Facial (keeps `Cumshot`) |
| Anal Fisting | also unparented from Anal Masturbation (keeps `Fisting`) |
| Femsub | Domination -> Submission (it was under the opposite concept) |
| Spit Roast | unparented from Spitting (position, not saliva play) |
| Hairless Labia | Trimmed Pussy -> Hairless Genitals (Female) |
| Small Penis | unparented from Average Penis |
| Public Sex | unparented from Public Nudity |
| Standing Blowjob / Standing 69 | unparented from Standing Sex (kept Blowjob / 69) |
| Hot Pants | unparented from Legwear and Leggings |

### New structure
- `Workflow` (1031): houses working tags — Missing Female/Male/Trans Performer,
  Missing Performer (both variants), Performer Review, review,
  Search for better version, missing scene search
- `Footwear` (1032): umbrella over `Shoes`, `High Heels`, `Boots`
- `Boots` (1033): generic boots under Footwear; Ankle/Platform/Cowboy Boots nested
- `High Heel Boots`: former `Boots` renamed; remains under `High Heels`

### Renames / merges
- `Interacial (X on Y)` x4 -> `Interracial (X on Y)`;
  `Interacial (Black on White)` merged via tagsMerge;
  `Interacial - Mixed` -> `Interracial - Mixed` (parented under Interracial)
- `Menstration` -> `Menstruation`; `Thongs` -> `Thongs (Footwear)`
- trailing spaces trimmed: `Bukkake`, `Self Cumshot`, `Standing Doggy`
- `Missing Male Performer - To Identify` merged into `Missing Performer - To identify`

### Destroyed
- Misspellings: cum in mouh, double facil, fack, hairkess, low qualt,
  streiptease, view from he
- Performer-name tags: jess harrington, sunshine ray
- Redundant umbrellas: `Tattoos & Piercings`, `Exotic`

### Preserved deliberately
- Plugin-dependent tags: `_DuplicateMarkForDeletion`, `_DuplicateWhitelistFile`,
  `_ExcludeDuplicateMarkForDeletion`, `[Set Profile Image]`,
  `[Stashbox Performer Gallery]`, `star identifier performer error`, `Image Studio`
  (DupFileManager, stashdb-performer-gallery, star_identifier all create/reference them)
- Transgender children (`Trans Fucks X`, `Trans Dildo`, `Trans Gape`, etc.) — user decision
- 30 unused tags kept: valid vocabulary, plugin deps, workflow parents

## Verification (final pass)
- Duplicates / whitespace / mojibake / cycles: none
- All reparent targets verified programmatically
- Newly-reparented co-tags (Submission+Femsub, Hairless Genitals+Hairless Labia): stripped
