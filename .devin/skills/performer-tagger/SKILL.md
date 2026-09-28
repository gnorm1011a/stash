---
name: performer-tagger
description: Extract performer names from gallery/scene filenames, cross-reference against Stash and StashDB, create missing performers, tag galleries, scrape metadata, and run auto-tag. Use when the user asks to identify, tag, or match performers in galleries or scenes by name extraction.
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

# Performer Tagger

Extract performer names from gallery/scene filenames or titles, cross-reference against existing Stash performers and StashDB, create missing performers with StashDB metadata, tag galleries, and run auto-tag.

## When to use

- When the user says "tag performers in [studio] galleries"
- When the user says "find performers from gallery names"
- When the user says "extract performer names from galleries"
- When the user says "match galleries to StashDB performers"
- When the user asks to identify and tag performers by filename/title analysis

## Prerequisites

- Stash running on `http://localhost:9999`
- StashDB endpoint configured (check via `configuration { general { stashBoxes { name endpoint api_key } } }`)
- The StashDB API key is stored in the Stash config; use the GraphQL endpoint from `stashBoxes[0].endpoint` and the API key from `stashBoxes[0].api_key` for StashDB queries

## Workflow

### Phase 1: Extract performer names

1. **Identify the target set.** Ask the user which studio, tag, or filter to target. Common options:
   - A specific studio (e.g., "XL Girls")
   - Galleries without performers
   - A specific path or directory

   For studios with child studios (e.g., "The Score Group" has Scoreland, XL Girls, 40 Something Mag, etc.), query the child studios as well:
   ```graphql
   query {
     findStudios(filter: { per_page: -1 }) {
       studios { id name child_studios { id name } }
     }
   }
   ```

2. **Query galleries.** Use the Stash GraphQL API to fetch galleries matching the target criteria. For each gallery, retrieve:
   - `id`
   - `title`
   - `folder { path }`
   - `files { path }`
   - `performers { id name }`
   - `studio { id name }`

   Example query:
   ```graphql
   query {
     findGalleries(filter: { per_page: -1 }) {
       galleries {
         id
         title
         folder { path }
         files { path }
         performers { id name }
         studio { id name }
       }
     }
   }
   ```

   **Note:** `findGalleries` supports `per_page: -1` to get all results. `findPerformers` does NOT support `-1` - you must paginate with `per_page: 1000` and `page: N`.

3. **Filter to untagged galleries.** Keep only galleries where `performers` is empty.

4. **Extract names from filenames/titles.** Gallery titles are often empty; the performer name is usually in the file path (zip filename) or folder path.

   **Important:** Do NOT rely on regex parsing alone - it produces many false positives (set titles get mistaken for performer names). Instead:
   - Read the raw filenames and manually extract names based on known patterns
   - Common patterns:
     - `18eighteen <SetTitle> - <PerformerName> (N Photos) - 18eighteen`
     - `18eighteen <PerformerName> - <SetTitle> - N Photos - 3000px - x<N> (Date)`
     - `Scoreland <SetTitle> - <PerformerName> (N Photos)`
     - `Scoreland <PerformerName> - <SetTitle>`
     - `XLGirls <SetTitle> - <PerformerName> (N Photos)`
     - `<PerformerName> - <SetTitle> - N Photos`
   - The performer name is typically:
     - The part between ` - ` and ` (N Photos)` when that pattern exists
     - The part after the studio prefix and before the first ` - ` when the name comes first
   - Skip single names (first name only) unless the user explicitly asks to include them
   - Skip names that are clearly not real names (e.g., "Alice85JJ", "Mila", "Riana")
   - Handle multi-performer galleries: `Alessandra Miller and Carlos Rios` → split on ` and `
   - Handle "performer name at end" patterns: `A Perfect Pair - Annabella May (57 Photos)`

5. **Present the extracted names to the user for confirmation.** Use `ask_user_question` to show the list and ask:
   - Are the extracted names correct?
   - Should any be added, removed, or corrected?
   - For galleries with single names - should these be included or skipped?

   **Do not proceed until the user confirms the name list.**

### Phase 2: Cross-reference against existing Stash performers

1. **Fetch all existing performers** from Stash. `findPerformers` does NOT support `per_page: -1` - you must paginate:
   ```graphql
   query {
     findPerformers(filter: { per_page: 1000, page: N }) {
       performers { id name alias_list }
     }
   }
   ```
   Fetch all pages until you have all performers (check `count` field on first query).

2. **Build a name lookup** including aliases. The field is `alias_list` (not `aliases`).

3. **Match extracted names** against existing performers (case-insensitive exact match on the trimmed name). Also check `alias_list` values.

4. **For unmatched names, do a fuzzy search** by first name and last name to catch potential variations or aliases.

5. **Present results to the user:**
   - Exact matches (performer already exists in Stash)
   - No match found (performer needs to be created)
   - Any ambiguous partial matches for user review

### Phase 3: Search StashDB for unmatched performers

1. **Get the StashDB endpoint and API key** from Stash configuration:
   ```graphql
   query {
     configuration {
       general {
         stashBoxes { name endpoint api_key }
       }
     }
   }
   ```

2. **Search StashDB** for each unmatched performer using the `searchPerformer` query:
   ```graphql
   query {
     searchPerformer(term: "Performer Name") {
       id
       name
       disambiguation
       aliases
     }
   }
   ```
   Send this to the StashDB GraphQL endpoint with `ApiKey: <api_key>` header.

   **Important:** When saving intermediate results to files, use a delimiter that won't conflict with the data (e.g., `|` conflicts with `|` characters in the response). Use JSON or a rare separator like `;;;` instead of `|`.

3. **Classify results:**
   - **Exact match** - single result with exact name, no disambiguation
   - **Disambiguation match** - exact name but multiple entries with different disambiguation (e.g., "Amber Marie (Scoreland)" vs "Amber Marie (Penthouse)")
   - **Alias match** - the searched name appears in the `aliases` array of a StashDB performer with a different primary name (e.g., "Laura Tithapia" is an alias of "Laura Boomlock")
   - **Partial match** - only first or last name matches, not the full name
   - **Not found** - no relevant results

   **Detection rules:**
   - Check `searchPerformer` results for exact name match on `name` field
   - If no exact match, check if the searched name appears in any result's `aliases` array
   - If multiple exact matches exist, check if they have different `disambiguation` values - these need user decision
   - If only one exact match exists (even if labeled "DISAMBIG" by the script), treat it as exact

4. **Present results to the user** with `ask_user_question`:
   - Show all exact matches (single StashDB entry)
   - For disambiguation matches (multiple entries with same name), show the disambiguation context and let the user choose
   - For alias matches, show the StashDB primary name and confirm the match
   - For not-found names, ask whether to skip or create a stub without StashDB data

   **Do not proceed until the user confirms which performers to create and which to skip.**

### Phase 4: Create performers and tag galleries

1. **Create performers in Stash** using `performerCreate` with the StashDB stash_id:
   ```graphql
   mutation {
     performerCreate(input: {
       name: "Performer Name"
       stash_ids: [{
         endpoint: "https://stashdb.org/graphql"
         stash_id: "<stashdb-uuid>"
       }]
     }) {
       id
       name
     }
   }
   ```

   **For alias matches:** Use the StashDB primary name (e.g., "Selena Rose") as the performer name, not the extracted name (e.g., "Sasha Bleu"). The extracted name can be added as an alias later if needed.

   **Handle "already exists" errors:** If `performerCreate` returns "performer with name X already exists", look up the existing performer ID via `findPerformers(filter: {q: "Name"})` and use that ID instead.

2. **Map galleries to performers.** Build a mapping of gallery ID -> performer ID(s). Some galleries have multiple performers.

3. **Tag galleries** using `galleryUpdate`:
   ```graphql
   mutation {
     galleryUpdate(input: {
       id: "123"
       performer_ids: ["456"]
     }) {
       id
       performers { id name }
     }
   }
   ```

   For galleries with existing performers, fetch the current performer IDs first and append (don't replace).

   **Note:** `galleryUpdate` uses `performer_ids` (with underscore), not `performers`.

4. **Verify each gallery** was tagged correctly by checking the returned performers.

### Phase 5: Scrape performer metadata from StashDB

**Linking is not scraping.** Setting `stash_ids` (via `performerCreate` or `performerUpdate`) only stores the ID — no metadata or image is pulled until `stashBoxBatchPerformerTag` runs. After ANY batch of stash_id assignments, always queue a tag job with `refresh: true`, then verify a sample of linked performers actually gained `country`/`birthdate`/image — silent partial failures are common and "linked but empty" performers are easy to miss.

1. **Run `stashBoxBatchPerformerTag`** to scrape metadata and images for all newly created performers:
   ```graphql
   mutation {
     stashBoxBatchPerformerTag(input: {
       stash_box_endpoint: "https://stashdb.org/graphql"
       performer_ids: ["4992", "4993", ...]
       refresh: true
       createParent: false
     })
   }
   ```

   This returns a job ID (a string like `"136"`). The job runs asynchronously.

   **Note:** The field is `performer_ids` (with underscore). The `refresh: true` flag means it will update existing performers.

2. **Wait for the job to complete.** Poll the job queue:
   ```graphql
   query {
     jobQueue { id status description progress }
   }
   ```
   Wait until status is no longer "RUNNING" (job queue returns `null` when complete).

   **Progress:** The job shows progress as a decimal (0.0 to 1.0). For ~139 performers it takes ~5-10 minutes.

3. **If some performers were not scraped** (missing image or country), run `stashBoxBatchPerformerTag` again for just those performer IDs. Some performers may need 2-3 attempts.

4. **Verify all performers** have images and metadata:
   ```graphql
   query {
     findPerformer(id: 4992) {
       name
       country
       image_path
     }
   }
   ```
   Check that `image_path` does not contain `default=true` (which means no image was set).

### Phase 6: Facial recognition pass (deferred, separate)

**Do NOT interleave face recognition with name research.** Star Identifier / face-embedding runs are expensive (minutes per batch) — run them ONCE at the end, after all name-based resolution is complete and the user has reviewed the results.

1. **Scope: every gallery still missing performers** — not just named stubs. This includes galleries where name extraction found nothing usable.

2. **Sample images** from each unresolved gallery (~4-5 evenly-spaced portraits — `files { height > width }` preferred), tag them with the `star identifier` tag, run the plugin's `Identify Images` task at tolerance 0.5.

3. **Tally hits per gallery.** Repeated hits across sampled images of the same performer = strong candidate. Single-image hits = noise; treat as "no face match found" unless corroborated.

4. **Present face-match candidates to the user before applying.** Face matches are proposals, not confirmations — the user has rejected several (e.g., ATK "Emily" split between two plausible lookalikes).

5. **For galleries still unresolved after the face pass:**
   - Named gallery → create/keep a plain stub performer (no stash_ids, no scrape), tag the gallery, and set a portrait image.
   - **Generic single-name stubs MUST get `ignore_auto_tag: true`** — names like "Sara", "Emily", "Dakota" would mass-tag unrelated files. Only skip the flag for distinctive single names (e.g., "Oksy").
   - Portrait image: pick a single-face image via `face_recognition.face_locations` (largest face area wins) — positional picking is unreliable.
   - Nameless gallery → leave untagged; a nameless stub is noise.

6. **Clean up the `star identifier` tag** (id may vary — look it up) from all sampled images/galleries after the run. Keep the tag entity itself for future runs.

### Phase 7: Run auto-tag
   ```graphql
   mutation {
     metadataAutoTag(input: {
       performers: ["4992", "4993", ...]
     })
   }
   ```

   **Note:** The field is `performers` (not `performer_ids`). This scans all scenes, images, and galleries for file paths matching the performer names and aliases.

   **Important:** Auto-tag runs on ALL content types (scenes, images, galleries) by default. It matches the performer name AND any aliases in file paths.

2. **Wait for the job to complete.** Poll the job queue until done:
   ```graphql
   query {
     jobQueue { id status description progress }
   }
   ```
   Auto-tag can take 10-20+ minutes depending on library size. The progress field shows 0.0 to 1.0.

### Phase 8: Verify

1. **Check each performer's counts** using `findPerformer`:
   ```graphql
   query {
     findPerformer(id: 4992) {
       name
       scene_count
       image_count
       gallery_count
       image_path
     }
   }
   ```

2. **Present a summary table** to the user showing:
   - Each performer name
   - Scene count, image count, gallery count
   - Total counts across all performers
   - Performers with 0 images (may need manual review or have no content in the library)

3. **Report any galleries still without performers** and explain why (single name, not in StashDB, user chose to skip).

4. **Check for StashDB-scraped metadata:**
   - `image_path` should NOT contain `default=true` (means image was scraped)
   - `country`, `birthdate`, `measurements`, `ethnicity` should be populated
   - If metadata is missing, re-run `stashBoxBatchPerformerTag` for that performer

### Stub naming: use `disambiguation`, not name suffixes

Stash supports duplicate performer names as long as `disambiguation` differs — the UI renders it as "Name (Disambiguation)". **Do NOT bake the studio into the name** (e.g., `Anfisa (Teen Funs)`); instead:

```graphql
performerCreate(input: {
  name: "Anfisa"
  disambiguation: "Teen Funs"
  gender: FEMALE
  ignore_auto_tag: true
})
```

Name-suffix stubs are harder to merge/link later and break name-based matching. (A 265-performer migration from `Name (Studio)` → `name` + `disambiguation` was needed in Sep 2026.)

**Also strip site prefixes from extracted names.** Filenames like `TeenStarsMagazine Ashley - Set 03`, `WowPorn.com Anjelica - Title`, `TSC Abby` must NOT produce `TeenStarsMagazine Ashley` as a name — strip the studio token first, then extract. If the surviving "name" still starts with the studio/site string, it's a parse bug, not a performer.

**Use the canonical studio spelling in `disambiguation`.** `Teen Stars Magazine`, `Total Super Cuties`, `Wow Porn` — not `TeenStarsMagazine`, `TotalSuperCuties`, `WowPorn`. When the site token is CamelCase, expand it to the studio's real name. This keeps the UI readable and lets `Name + disambiguation` uniqueness work correctly.

**When a gallery leaf starts with a site name, also set `studio_id`** on the gallery (create the studio first if missing). `NikkiSims Chrissy` → studio "Nikki Sims" + performer `Chrissy [Nikki Sims]`.

### Two-name galleries are two performers

Folders like `Nansy Bianka`, `Freya Chloe`, `Katrina Tata`, `Linda Bianka` are duo sets, not single people. Split on the space and tag both performers — never create a combined stub like "Freya Chloe". Conversely, `X aka Y` (e.g., `Charlene B aka Mandy Dee`) is ONE performer — use the better-known name and put the site name in `alias_list`.

**Studio visit numbers (`Name II`, `Name III`) are the same person.** FTV and similar sites append roman numerals for repeat shoots — `Scarlett III`, `Scarlett IV` are the same model on her 3rd/4th visit. Fold them into the base performer (`Scarlett Hampton`) with the numbered names as `alias_list` entries; do not create separate stubs.

**Check StashDB aliases for stubs too.** A stub created for a name that exists only as a StashDB alias is a missed link (e.g., `Melissa Manzoni` → real name `Milana Frajerova`). Before leaving a stub unlinked, run `searchPerformer(term: "<name>")` and check both `name` and `aliases` on every result — an alias hit is a valid link even when the local name is single-word.

### Filename formats vary per archive — parse leaves, not patterns

The same studio ships galleries as `TeenFuns Name - #NN`, `TeenFuns.com NNN - Name`, `TEEN FUNS - Name - NNN`, `AmourAngels DD-MM-YYYY-Presenting Name`, `OlderWomanFun Name - Name NN - MMDDYYYY`. Extract the leaf folder name, then apply multiple patterns in order of specificity. When folder names are generic (`Re Studio - Collection`, `Year 2017.N`), check `findImages` file basenames — names often live there (`sb_kim_seductive_shapes_2017_001.jpg`). Galleries whose filenames are 3-letter codes (`bea001`, `lca005`) or pure numbers are unresolvable by name — leave untagged for the face pass.

### Local name-only matches on generic first names are wrong-person traps

Matching `Joy` → local `Joy [Pascals Sub Sluts]` (b. 2001) for an OlderWomanFun gallery was wrong — different person entirely. Before tagging a bare first name to an existing local performer: sanity-check plausibility (birthdate/era vs the set's era, site type). When in doubt, create a disambiguated stub — merging later is cheap, untagging wrong galleries is not.

**Hard rule (Sep 2026, Bootylicious incident):** a single extracted name must NEVER be auto-tagged to an existing performer — not even when the local match looks plausible or the performer is StashDB-linked. Alias-list hits are NOT exact matches either (`Toni` is an alias of male performer `Emilio Ardana`; `Naomi` matched `Naomi [Canadian]` but the gallery was Naomi Russell). Default action for single names: create a local `Name [Studio]` stub with `ignore_auto_tag: true`. Only tag an existing performer when there is explicit corroborating evidence — e.g. the local record's `disambiguation` already names this studio (`Sensuous [Bootylicious]`), or the user confirms. Anything merely plausible goes to the `review` tag. Same for alias-hit matches on multi-word names (`Barbie Banx` → `Barbie Banxxx`): treat as review, not auto-tag. The Sep 2026 Bootylicious batch required ~25 manual reverts from exactly this failure mode.

### Serialized execution & reliability rules

- **One face-recognition process at a time, ever.** Two concurrent `face_recognition` passes exhausted the CPU and crashed the box requiring a reboot. This includes Star Identifier plugin runs — never overlap them.
- **Portrait generation in batches of 5-10, never 100+.** Use `number_of_times_to_upsample=0` and skip files > ~30MB — upsampling an 8000px scan hangs the process for 30+ min with zero output.
- **Long-running Python must write a flushed log file** (`open(..., 'a')` + `flush()`), not rely on piped stdout — a crashed process takes all buffered output with it.
- **Update-hook plugins multiply batch mutations into API floods.** `tagImagesFromGalleries`, `tagImagesWithPerfTags`, and `stashdb-performer-gallery` each spawn a new python process per Gallery/Image/Performer update — including updates made BY other plugins (cascade). ~65 galleryUpdates once produced 23 concurrent plugin processes and 1,000+ connections, slowing the API to 60s+/query. Before any batch run: warn the user that hook plugins are active (offer to disable them in Settings → Plugins first), count `tasklist | grep python3.9` during the run, and kill stray plugin processes (`Get-Process python3.9 | Stop-Process`) if a storm builds. `Image.Update.Post` triggers were trimmed from two plugins on 2026-09-18 to break the cascade; the yml comments document restoration.
- **Make every script idempotent:** check for an existing performer (name + disambiguation) before create, skip performers that already have portraits, and never assume a mutation succeeded — check the response.
- **Transient `HTTP 422` on `performerCreate` can occur while another script is renaming performers** (uniqueness race). Retry with a delay before giving up.
- **Don't put GraphQL in PowerShell strings** — `$` inside double-quoted strings gets interpolated and fails. Write .py files and run them.
- **Check the StashDB studio name variants.** `ClubSeventeen` isn't on StashDB — it's `Club Sweethearts`. Search `queryStudios` with 2-3 spellings before concluding there's no roster.
- **After `stashBoxBatchPerformerTag`**, scrape rewrites names to the StashDB canonical form (e.g., `Matty` → `Matty Mila Perez`) — re-add the site name via `alias_list` so filename matching still works.
- **A wrong stash link costs the portrait too.** The scrape overwrites `image` with the wrong person's StashDB photo. To revert: clear `stash_ids`, restore `name`/`disambiguation` from the recorded local values, drop the local name from `alias_list` (rename fails on "duplicate alias" otherwise), then regenerate the portrait.
- **Reverting must also clear scraped metadata.** `stash_ids: []` does NOT undo a scrape — tattoos, piercings, birthdate, country, career_length, measurements, height_cm, weight, eye_color, hair_color, fake_tits, ethnicity, urls, and details all persist as wrong-person data. On revert, clear them: strings take `""`, `urls` takes `[]`, and `birthdate`/`career_length`/`height_cm`/`weight`/`death_date`/`circumcised`/`penis_length` take `null` (empty string fails on career_length — "empty year range string"). Always re-verify `stash_ids` is empty before clearing so you never wipe a legitimately linked performer.
- **Fast portrait regen:** don't re-run `face_recognition` for bulk portrait fixes — pick the first portrait-oriented (`height > width`) image in the performer's first gallery and set it via `performerUpdate(image: base64)`. ~10x faster than face detection and good enough; refine manually later.
- **`stashBoxBatchStudioTag` uses `stash_ids`** (StashDB UUIDs), not local `studio_ids` — passing local IDs silently fails.
- **Title-baked names are parse bugs.** If a performer name contains verbs/scene words (`Has Fun At`, `Sexy Fitness Time`, `loves anal`, `with her heels on`), the extractor swallowed the scene title — the real name is usually the leading token(s). Scan for these with a title-word regex before and after batch creation.

## GraphQL request pattern

Stash GraphQL requests use this PowerShell pattern:
```powershell
$query = "mutation { ... }"
$body = @{ query = $query } | ConvertTo-Json -Compress
[System.IO.File]::WriteAllText("C:\Users\adam\AppData\Local\Temp\stash_query.json", $body)
$raw = curl.exe -s -X POST http://localhost:9999/graphql -H "Content-Type: application/json" --data-binary "@C:\Users\adam\AppData\Local\Temp\stash_query.json"
```

StashDB GraphQL requests add the API key header:
```powershell
$raw = curl.exe -s -X POST $stashdbUrl -H "Content-Type: application/json" -H "ApiKey: $apiKey" --data-binary "@C:\Users\adam\AppData\Local\Temp\stashdb_query.json"
```

## Key rules

- **Name research first, face recognition last.** The pipeline is: extract names → local matches → StashDB → deep research (aliases/misspellings/FreeOnes/web) → **STOP for user review** → then one bulk face-recognition pass over all still-untagged galleries → stubs + portraits. Never invoke Star Identifier mid-pipeline.
- **Always confirm extracted names with the user before proceeding.** Do not auto-create performers without user approval.
- **Always confirm disambiguation choices with the user.** When multiple StashDB performers have the same name, show the disambiguation context and let the user choose.
- **Do not tag galleries for disambiguated or uncertain matches** unless the user explicitly approves.
- **Skip single-name performers** (first name only) by default, unless the user asks to include them.
- **Use `galleryUpdate` (not `bulkGalleryUpdate`) for tagging** when each gallery has different performers. Use `bulkGalleryUpdate` only when applying the same change to many galleries.
- **Always verify results** after each phase - don't assume a mutation succeeded without checking the response.
- **The StashDB API key is sensitive.** Do not log it or include it in output. Retrieve it from Stash config at runtime.
- **Rate-limit StashDB requests.** Add a small delay (200-300ms) between StashDB API calls to avoid hitting rate limits.
- **NEVER blind-link single-word names to StashDB.** A local stub `Amy` matching a StashDB `Amy` is almost always a different person — hundreds of wrong links were created this way and had to be reverted (including wiped portraits). Only auto-link when the match has ≥2 name words AND exact-name equality, or an alias hit where the local name has ≥2 words. Everything else (single names, fuzzy/variant names, disambiguation mismatches like `Jenn (2006, Pink Visual)` vs local studio) goes to the `review` tag for the user, never straight to a stash_id.
- **Uncertain alias/fuzzy matches get a parallel candidate performer, not an in-place link.** When a local stub might be a StashDB performer under a different name (`Krystle` → `Whitney Prescott`), do NOT rename/link the existing stub — the scrape then overwrites the local name, disambiguation, and thumbnail with the wrong person's data. Instead:
  1. Create a NEW performer with the StashDB name + stash_id + `review` tag (id 1001), leave the local stub untouched.
  2. Present candidates to the user; on confirmation, move galleries to the linked performer, copy the local name into its `alias_list`, then destroy the stub.
  3. On rejection, destroy the candidate — the stub survives intact with its portrait.
- **Use the correct field names:** `alias_list` (not `aliases`), `performer_ids` in `galleryUpdate`, `performers` in `metadataAutoTag`, `stash_box_endpoint` in `stashBoxBatchPerformerTag`.
- **Paginate `findPerformers`** - it does not support `per_page: -1`. Use `per_page: 1000` and iterate pages.
- **When saving intermediate results to files**, use JSON or a rare delimiter (like `;;;`) to avoid conflicts with `|` or other characters in the data.
- **For long-running jobs**, poll `jobQueue` for status and progress. Show progress to the user periodically.
- **Check `image_path` for `default=true`** to verify a performer image was scraped successfully.
