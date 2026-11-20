# Collection Naming Rules

Conventions for file names under `\\192.168.0.31\Collection\Video`. Segments are
joined with ` - `. `(NNN)` is the vertical-resolution suffix.

## Order of segments

1. **Performer(s)** — when known. Always lead. `Name - Name - …`
2. **Studio/site brand** — when no performers are known but a brand is
   (`Facial Abuse`, `Freaks of Boobs`, `Bustyz`, `Max Hardcore`…)
3. **UI** — placeholder for unknown performer(s)
4. **Movie title / scene description**
5. **`Scene N`** — movie-scene files only
6. `(NNN)` resolution suffix

## Canonical forms

| Case | Form | Example |
|---|---|---|
| Known performers, movie scene | `Perf(s) - Movie - Scene N` | `Austin Kincaid - Mark Davis - Ready Wet Go #1 - Scene 3` |
| Known performers, clip | `Perf(s) - Studio - Description` | `Asa Akira - Erik Everhard - Elegant Angel - Seduction` |
| Unknown cast, movie scene | `UI - Movie - Scene N` | `UI - Sperm Overload 3 - Scene 7` |
| Unknown cast, studio brand | `Studio - UI - Description` | `Facial Abuse - UI - Cali Rider` |
| Unknown cast, no brand | `UI - Description` | `UI - Hong Kong Dong` |

## Rules

- **Performers always lead** — never appended after the movie/scene title.
- **UI never trails** a scene name when cast is unknown — it leads (or follows
  the studio brand for branded clips).
- **Studio + UI order**: brand first, UI second — the brand is real metadata,
  UI is a placeholder and must not push the brand out of position.
- **Movie/scene structure preserved** — `Movie - Scene N` is never broken up
  or reordered; performers go in front of it, UI leads the whole name.
- **No invented names** — UI stays until an authoritative source (fingerprint
  match, StashDB, per-scene DVD listing) identifies the cast.
- **Manual names are authoritative** — files not matching a generated name are
  never overwritten; only flagged for review.
- **Performer names are canonical** — no `(Studio)` suffixes or prefixes in the
  performer segment; studio context belongs in its own segment.
