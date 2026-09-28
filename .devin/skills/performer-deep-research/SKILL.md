---
name: performer-deep-research
description: Deep research for performers with no StashDB match. Uses alternate databases (Boobpedia, Freeones, Babepedia, IAFD), StashDB studio rosters, fuzzy matching, face verification, and web search to find candidate StashDB entries or aliases. Confidence-tiered — high-confidence matches auto-applied only after user approval, everything else flagged for review. Use when performer names fail StashDB lookup.
triggers:
  - user
  - model
allowed-tools:
  - read
  - grep
  - glob
  - exec
  - ask_user_question
  - todo_write
  - web_search
  - webfetch
---

# Performer Deep Research

Research performers who have no StashDB match (e.g., PARTIAL/NOTFOUND results from performer-tagger, or stub performers). Uses alternate performer databases, StashDB studio rosters, and face verification to find candidate matches.

**Core principle: research before mutation.** Run this on the unmatched-name list *before* creating stub performers. Never link `stash_id`, scrape, or rename before the user approves a candidate.

## When to use

- During `performer-tagger`, on the PARTIAL/NOTFOUND list — **before** creating stubs
- When the user asks to "research", "deep search", or "find aliases" for a performer
- When a name exists locally but has no StashDB link

## Prerequisites

- Stash running on `http://localhost:9999`
- StashDB configured in `configuration { general { stashBoxes } }`
- Star Identifier plugin (face matching) — optional but strongly recommended for verification

## Data sources

### Working NAME-search scrapers (verified)

| Scraper ID | Source | Notes |
|---|---|---|
| `Boobpedia` | boobpedia.com | Best for aliases — URL scrape returns `aliases` field |
| `builtin_freeones` | freeones.com | Reliable name search, full bio on URL scrape |
| `AdultEmpire` | adultempire.com | Works but often empty for amateur/niche models |

### Broken scrapers (as of Sep 2026)

- `Babepedia` — "could not unmarshal json: EOF" (missing deps or stale YAML)
- `IAFD` — same EOF error

### StashDB studio roster

StashDB supports filtering performers by studio — the highest-signal data source for studio-specific research:

```graphql
query { findStudio(name: "Cosmid") { id name } }

query {
  queryPerformers(input: {
    studio_id: "<studio-uuid>"
    per_page: 100
    page: 1
    direction: ASC
    sort: NAME
  }) {
    count
    performers { id name disambiguation aliases }
  }
}
```

This returns every performer with at least one scene tagged to that studio — an authoritative roster. **A fuzzy name match inside the studio roster is far stronger evidence than a name match on the open web.**

## Confidence tiers

Score every candidate before presenting. Apply mutations only after user approval.

| Tier | Criteria | Action |
|---|---|---|
| **Auto-apply** (after approval) | Studio-roster match dist ≤ 1, OR multi-word alias exact match on StashDB, OR face-verified | Link stash_id + scrape |
| **Flag for review** | Roster dist 2-3, single strong alias, FreeOnes-only match | Tag performer, record candidate in `details`, no linking |
| **Discard** | Single-name alias hits ("Ava", "Kira"), no roster presence, name-only FreeOnes match on common names | Skip |

## Workflow

### Phase 1: Build the research list

Input = unmatched names from performer-tagger (PARTIAL/NOTFOUND). **Do not create stub performers yet** — research first so verified matches are created already-linked and false guesses never become performers.

If stubs already exist, use them (name + Stash ID).

### Phase 2: Alias discovery via scrapers

For each name:

1. **Name search:**
   ```graphql
   query {
     scrapeSinglePerformer(
       source: { scraper_id: "Boobpedia" }
       input: { query: "Performer Name" }
     ) { name url }
   }
   ```

2. **URL scrape** on hits for full bio:
   ```graphql
   query {
     scrapePerformerURL(url: "<result-url>") {
       name aliases country birthdate ethnicity measurements career_length image
     }
   }
   ```
   `aliases` is a comma-separated string — split on `,`.

3. **Filter candidate names BEFORE re-searching StashDB:**
   - Keep: multi-word aliases, distinctive single names
   - **Discard: single-name aliases** ("Ava", "Scarlet", "Kira") — they match hundreds of unrelated StashDB entries and produce pure noise. In the Cosmid run, all four single-name alias hits were false positives.

### Phase 3: StashDB re-search with expanded names

```graphql
query {
  searchPerformer(term: "Candidate Name") {
    id name disambiguation aliases
  }
}
```

- Exact `name` match or `aliases` match → candidate
- Multiple results → check `disambiguation` for studio tags (e.g., `[Cosmid]`)

### Phase 4: Studio roster fuzzy match

1. `findStudio(name: "<studio>")` → studio UUID — **also fetch `child_studios` and query every child's roster too.** Studio networks model sub-brands as child studios on StashDB (e.g., ATKingdom → ATK Archives, ATK Exotics, ATK Galleria, ATK Girlfriends, ATK Lingerie, ATK Mature, ATK Natural & Hairy, ATK Petites, ATK Premium, ATK Uniforms, AMK Empire). The parent roster alone is near-empty; the combined children are the real coverage. **Mirror check locally too:** untagged galleries may sit on separate local sub-studio entries (`findStudios q:"ATK"`), not the parent studio — scope the whole family, not just the studio ID the user named.
2. `queryPerformers(input: { studio_id })` → paginate `per_page: 100` for each studio in the family
3. Levenshtein-match each remaining name against roster names + aliases:

   ```python
   def lev(s, t):
       s, t = s.lower(), t.lower()
       m, n = len(s), len(t)
       if m == 0: return n
       if n == 0: return m
       prev = list(range(n+1))
       for i in range(1, m+1):
           curr = [i] + [0]*n
           for j in range(1, n+1):
               cost = 0 if s[i-1] == t[j-1] else 1
               curr[j] = min(prev[j]+1, curr[j-1]+1, prev[j-1]+cost)
           prev = curr
       return prev[n]
   ```

   - `dist ≤ 1` → strong (spelling variant, e.g., "Allies Giovanni" → "Allie Giovanni")
   - `dist ≤ 2` → possible
   - `dist > 2` → discard

### Phase 5: Lightweight corroboration (no face recognition here)

**Face recognition does NOT belong in this loop** — it is deferred to a single bulk pass after user review (see below). During name research, corroborate cheaply instead:

- Does the external bio mention the studio?
- Do career dates overlap the gallery/set dates?
- Do measurements/ethnicity look plausible?
- ATK-specific: does the StashDB `disambiguation` carry the model code seen in the gallery's image filenames (e.g., `luc050`)?

Cheap per-candidate face checks (single profile image vs a few gallery frames via `face_recognition`) are acceptable as a *tiebreaker* — they are fast. What is NOT acceptable here is running the Star Identifier plugin (encodings DB scan) mid-research — batch it at the end.

### Phase 6: Present candidates, get approval

Present a table to the user:

| Local name | Candidate | Found via | Tier |
|---|---|---|---|

Wait for explicit approval. User's pick applies only to the exact candidates presented.

### Phase 7: Apply (approved candidates only)

For approved candidates:

1. If a stub exists: `performerUpdate` to add `stash_ids`, then `stashBoxBatchPerformerTag` (refresh) to pull metadata/image.
2. If no stub exists: `performerCreate` with `stash_ids` included, then batch scrape.
3. **After scrape, restore the original (studio) name as an alias** — the refresh renames to the StashDB primary name and drops the local name, which breaks auto-tag matching on filenames:
   ```graphql
   mutation { performerUpdate(input: { id: "<id>", alias_list: ["<existing>", "<original-name>"] }) { id } }
   ```
4. Check for duplicates first: if the candidate's stash_id is already on an existing local performer, merge instead — add the stub name as an alias on the existing performer, retag galleries/images (`bulkImageUpdate` REMOVE/ADD), then `performerDestroy` the stub.

### Phase 8: FreeOnes fallback (no StashDB candidate)

For names with no StashDB candidate at all, FreeOnes provides bio + profile URL:

1. `builtin_freeones` name search → profile URL
2. `scrapePerformerURL` → full bio + base64 `image`
3. Update performer: `urls`, `gender`, `birthdate`, `country`, `ethnicity`, `measurements`, `height_cm` (NOT `height`), `weight`, `tattoos`, `piercings`, `career_length` (sanitize `"2017-now"` → `"2017-"`), `alias_list` (array, not comma-string), `image`
4. **Caution:** a FreeOnes name match on a common name is weak evidence — verify via studio mention in bio, career-date overlap, or face comparison before treating as confirmed.

### Phase 9: Bulk face pass (after user review)

Run once over **every gallery still missing a performer** — named stubs and no-name galleries alike — not per-name during research. See performer-tagger "Facial recognition pass" for the mechanics (star identifier tag → sample → Identify Images at 0.5 → tally → present candidates).

### Phase 10: Unmatched stubs — populate basics

For stubs with no match anywhere:

- `gender: FEMALE` (or appropriate)
- **Use `disambiguation` for the studio/site, not a name suffix** — `name: "Anfisa", disambiguation: "Teen Funs"` (Stash allows duplicate names when disambiguation differs; the UI renders it as "Anfisa (Teen Funs)"). Never create `Anfisa (Teen Funs)` as the name — it breaks merging and name matching.
- **Generic/single-name stubs MUST get `ignore_auto_tag: true`** — names like "Sara", "Sandra", "Lucie" will otherwise match hundreds of unrelated filenames/paths during auto-tag and produce mass false tagging. Only skip this for distinctive single names (e.g., "Oksy").
- Portrait image from one of their galleries: `findImages` sorted `created_at` ASC, pick a portrait-orientation (`height > width`) image, download via `http://localhost:9999/image/<id>/image`, base64 → `performerUpdate { image }`.
- **Positional picking is unreliable** — expect rejection rounds. Better: run `face_recognition.face_locations` on a window of candidates and pick the single-face image with the largest face area, or present a 4-6 image contact sheet for one-click selection.

## Cleanup after review

The review workflow leaves residue. After the user finishes reviewing:

- Remove the review tag from all performers (`performerUpdate` with `tag_ids` minus the review tag — preserve other tags).
- Clear `details` notes (`details: ""`).
- Delete the review tag entity itself if no longer needed (`tagDestroy`).
- Rejected FreeOnes links: strip `urls`, scraped fields, and image; keep the stub (name is still correct).
- Rejected StashDB links: the scrape renamed the performer — either revert name or delete the performer entirely if the whole match was wrong (deletion cascades image/gallery associations).

## Key rules

- **Research before creating stubs.** Verified matches get created already-linked; false guesses never become performers.
- **Never link/scrape/rename before user approval.** Candidates are presented, then applied.
- **Filter single-name aliases before StashDB re-search** — they're pure noise.
- **Studio roster fuzzy match is the strongest signal.** Prefer it over open-web name matches.
- **Face-verify when possible.** Star Identifier or image comparison turns guesses into confirmations.
- **Restore original names as aliases after refresh** — `stashBoxBatchPerformerTag(refresh: true)` renames to the StashDB primary and loses the local name.
- **Rate-limit:** ~300-500ms between scraper calls, ~200ms between StashDB calls.
- **Never log the StashDB API key** — retrieve from Stash config at runtime.

## Example outcome (Cosmid test run, Sep 2026)

From 50 unmatched names:

- 12 candidates found; **9 verified correct** by user (Allie Giovanni, Jasmine Hall, Lana Wolf, Victoria Mur, Foxxy Star, Scarlett Jones, Brooke Scott, Miss Mila Rose, Tierra — the last later rejected)
- 2 duplicates caught: Emma Sirruss = Emma Sirus, Natalie Parkman = Natalie Porkman
- 3-4 false positives flagged by user review (would have been caught by face verification)
- 21 of remaining 37 got FreeOnes profile data; 16 had no match anywhere
- Lesson: studio-roster matches were ~100% accurate; open-web name matches ~60% accurate

### ATKingdom run (Sep 2026)

- 85 galleries → 44 names. 10 local matches, 25 clean StashDB hits, 3 user-resolved (incl. one FreeOnes-only match: Megyn Mason)
- **Watch for same-name wrong-gender StashDB entries:** `Dakota James` has both a MALE entry (disambiguation "[ATKingdom]") and a FEMALE one — the disambiguation tag meant the *site*, not the roster-verified model. Always check `gender` on the StashDB result before linking.
- **StashDB disambiguation contains ATK model codes** (`Lucie [ATKingdom, luc050]` matches the `(luc050)`/`oks010` codes in ATK folder names) — a strong lead generator for single-name models.
- **But codes still need face verification:** `luc050` face-compared at 0.82 distance — wrong person, link reverted.
- Face-verification against StashDB profile images resolved 2 of 6 single-name stubs (Gigi → Cosprincess Gigi 4/4 hits @ 0.354, Conny → Connie Carter 2/4 @ 0.475). Remaining single-name stubs (Lucie, Oksy, Sandra, Sara) had no candidate anywhere — expected, common names on a huge network.
- Generic single-name stubs were flagged `ignore_auto_tag` to prevent mass false-tagging.
