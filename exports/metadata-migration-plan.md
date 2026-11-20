# Stash metadata migration plan (v2 — post-review)

## Context (corrected scope — verified live)

- **3,611 scenes** have ≥1 missing file entry; **3,484** have ALL files missing
- **2,633 stale scenes carry curated metadata** (performers 2,351; tags 2,527; stash_ids 922; titles 1,123; details 855; studios 1,451; urls 1,012; dates 1,027; groups 184; ratings 99; organized 58)
- **193 stale scenes have 1,480 markers**
- 302 stale scenes have play history (335 plays); 10 have o_counter>0
- Stale paths: ~2,791 under `Video/` (mostly renamed mp4s), 878 under `Video/Old Collection`, 23 under `Video/Max Hardcore`, ~10 under `Unfiled`
- Stash v0.31.1; parallelTasks:1; oshash naming algorithm

## Key semantics (verified against Stash source)

- `sceneMerge(source:[ID!], destination, values:SceneUpdateInput, play_history, o_history)`
  - `values` is REQUIRED — merge does NOT auto-carry metadata. List fields are SET-mode: compute union(src, dest) client-side
  - `play_history`/`o_history` flags are the ONLY carrier for counts — always true
  - Auto-transfers: file entries, markers (incl. screenshot renames), source destroyed (disk/files safe)
  - Self-merge errors — must skip pairs where scan self-healed the scene
- Scan self-heal: renamed/moved files with same content → fingerprint match → old file entry repathed IN PLACE. No new scene, no merge needed. Only re-encoded mp4s (~750) create new scenes
- `metadataScan(paths)` accepts any subdir under a configured stash; `/mnt/Nasferatu/Collection/Video` and `/Unfiled` are configured stashes
- `metadataClean(paths, dryRun)` — dryRun logs "Marking to clean" to job log; destroys scene iff it has no remaining files. MUST run AFTER merges
- `findScenes` path filter ORs whitespace-separated words — quote multi-word paths or use MATCHES_REGEX
- Plugin hooks fire on Scene.Create.Post (scan) and Scene.Update.Post (merge): attribute_tag_sync, markerTagToScene, setPerformersFromTags, tagScenesWithPerfTags, TPDBMarkers — review/disable during run

## Path mapping (old → new)

Normalize mixed separators; map `//192.168.0.31/Collection` → `/mnt/Nasferatu/Collection`.
Chains from: `wmv-convert-log.jsonl` (ext swap), `rename-perf-typos-log.json`, `rename-safe-fixes-log.json`, `rename-residual-spaces-log.json`, `rename-dup-flags-log.json`, `rename-applied-log.json` (OC renames), OC flatten/move (sub→root, OC→Video root, basename preserved).

## Phases

### 0. Backup + snapshot (read-only)
- `backupDatabase` mutation → DB snapshot before any change
- Dump all 3,611 stale scenes: full metadata + play/o date arrays + full marker records (findSceneMarkers for the 193) → `exports/stale-snapshot-<ts>.json`

### 1. Targeted scan
`metadataScan(paths:["/mnt/Nasferatu/Collection/Video","/mnt/Nasferatu/Collection/Unfiled"], all generate flags OFF)`
- Self-heals ~2,700 renamed/moved files; creates ~750 new scenes for re-encodes
- Disable Scene.*.Post plugin hooks first if feasible (check plugin config)

### 2. Match
For each still-stale scene: old path → rename-log chain → new path → findScene by file path.
- If found id == stale id → self-healed, skip
- Ambiguous/dup fingerprint cases → review list
- Output: `exports/migration-match-<ts>.json` (stale→new | self-healed | unmatched-deleted | ambiguous)

### 3. Merge
Per pair: `sceneMerge(source:[stale], destination:new, values:{id:new, title?, code?, details?, director?, urls union, date?, rating100?, organized?, studio_id?, performer_ids union, tag_ids union, gallery_ids union, groups union, stash_ids deduped-by-endpoint}, play_history:true, o_history:true)`
- Scalar fields: prefer non-empty stale value when dest is empty/default; when both set → keep stale (curated) but record conflict in log for review
- cover_image: fetch `paths.cover` of stale scene if custom; else rely on Phase 4
- Batch ~50/log; verify samples manually; log all → `exports/migration-merge-log-<ts>.json`

### 4. Targeted generation
`metadataGenerate(sceneIDs:[new/migrated scene ids], covers:true, sprites:true, previews:true)` — id-scoped only

### 5. Clean (after user review)
`metadataClean(paths:[Video, Unfiled], dryRun:true)` → extract "Marking to clean" from logs → user confirms → real run. Removes records for genuinely deleted files (zero-stubs, junk) and ghost file entries left on merged scenes.

## Safety

- Disk untouched; DB backup + JSON snapshot before mutations
- Clean only after dryRun list review
- All calls path- or id-scoped; no library-wide generate/tag/clean
- parallelTasks:1 — scan is hours; phases sequential
