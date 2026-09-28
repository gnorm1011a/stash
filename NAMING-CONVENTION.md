# Video File Naming Convention

This document defines the preferred filename convention for video files in the
`\\192.168.0.31\Collection\Video\` library. It was derived by analysing the
~12,300 already‑finished files in `Collection\Video\` and aligning them with the
curated metadata stored in the Stash database (exported to `exports/` in this
repo).

The convention exists so that a file's identity can be read at a glance and so
that files can be reliably matched back to their Stash scene record (performers,
studio, movie, tags) for re‑scanning and auto‑tagging.

---

## 1. Canonical pattern

```
<Performer(s)> - <Studio> - <Scene description> (<resolution>).<ext>
```

Fields are separated by ` - ` (space‑hyphen‑space). The fields are, in order:

| # | Field | Required | Source in Stash |
|---|-------|----------|-----------------|
| 1 | **Performer name(s)** | Yes (see §4 for exceptions) | `performers[]` on the scene; canonical names from `exports/performers.json` |
| 2 | **Studio** | Optional — only if known | `studio` on the scene; names from `exports/studios.json` |
| 3 | **Scene description** | Yes | Derived from scene `title`, `movies[].movieName`, or `tags[]` |
| 4 | **Resolution** | Optional but strongly preferred | Vertical pixel height of the source file, in parentheses |

### Multiple performers

When a scene has more than one performer, list each performer name separated by
` - `, in the same order they appear in the Stash `performers[]` array:

```
Monica Santhiago - Sara Jay - Share BBC (1080).mp4
Trina Michaels - Tyla Wynn - Butt Licking Anal Whores 2 (1080).mp4
August Ames - Ashley Adams - Naughty Office (720).mp4
```

### With a studio

Insert the studio name after the performer(s) and before the description:

```
Brooke Lee Adams - Elegant Angel - BWA (1080).mp4
Remy Lacroix - Elegant Angel - BWA 1 (1080).mp4
Nikki Benz - Jules Jordan - 4K (2160).mp4
Anna Bell Peaks - MYLF - Body - Track And Feel (1080).mp4
Sofia Lee - DDF - Doubled Up Thick BBW (1080).mp4
Zoey Andrews - Plumper Pass (720).mp4
```

### Performer + male performer/director + studio + description

When a male performer or director is credited as a co‑identifier (common for
director‑branded series), they occupy the second slot, followed by the studio,
then the description:

```
Bella Bellz - Kieran Lee - Brazzers - Huge Ass Bad Bitch Gets Anal (1080).mp4
Aurora Snow - Tom Byron - Grand Theft Anal 9 (1080).mp4
Danielle Derek - Mark Ashley - Gets Anal Creampie (720).mp4
```

---

## 2. Ordering modes observed in the library

The finished library uses three leading‑token modes. Use the one that best
reflects how the scene is identified:

### Mode A — Performer‑led (default)

Use when the performer is the primary identifier. This is the canonical form
from §1.

```
Jessica Moore - More Than A Handful - Three On One 049 (720).mp4
Madi Collins - Young Redhead Eats some Ass.mp4
```

### Mode B — Category‑led

Use when the scene is best grouped by an ethnicity/type category that is **not**
a Stash studio. The category is a free‑text prefix; the rest of the pattern is
unchanged.

Observed category prefixes and approximate frequency in the current library:

| Prefix | Count | Prefix | Count |
|--------|-------|--------|-------|
| Euro | 642 | Black | 112 |
| Teen | 469 | Latina | 111 |
| Asian | 404 | Amateur | 153 |
| Russian | 352 | Compilation | 184 |
| Brazilian | 288 | TS | 91 |

Examples:

```
Russian - Mandy Dee - Analyzed_Teens_2_Scene_2.mp4
Asian - Arcadia Davida - Assfensive_5_Scene_1.mp4
Black - Sasha Rae - Elegant Angel - BBWA (480).mp4
Euro - Jada Sparks - Pornbox - Anal Piss Gangbang (1080).mp4
Compilation - Club Tug - Handjob Cumshots Compilation (720).mp4
```

### Mode C — Studio/Series‑led

Use when the studio or series **is** the primary identifier and the performer is
unknown, generic, or secondary to the brand. The studio takes the first slot
(this is a Stash studio, not a free‑text category).

Observed series/studio prefixes: `Facial Abuse`, `Hookup Hotshot`, `GGG`,
`First Anal Quest`, `Mini Skirt Girlz`, `Mom POV`, `BRCC`, `Young Throats`,
`Scores`, `UI`, etc.

```
Hookup Hotshot - Khloe Kapri (1080).mp4
Facial Abuse - Mona Jade Interracial (720).mp4
BRCC - Sophia Sterling - Petite Cool Blonde Anal Creampie (1080).mp4
Young Throats - 9.3 (720).mp4
```

> **Choosing A vs C:** If the performer is named and recognised in Stash, prefer
> Mode A (performer first). Only lead with the studio when the performer is
> genuinely unknown or the series brand is the way the scene is canonically
> referenced (e.g. `Facial Abuse`, `GGG`).

---

## 3. Resolution suffix

Append the source vertical resolution in parentheses, immediately before the
extension. Use the actual encoded height, not a marketing label.

| Suffix | Meaning | Library frequency |
|--------|---------|-------------------|
| `(2160)` | 4K UHD | ~200 |
| `(1440)` | 2K / 1440p | ~400 |
| `(1080)` | Full HD | ~4,050 |
| `(720)` | HD | ~2,680 |
| `(480)` | SD / DVD | ~680 |
| `(360)` | web/low | ~47 |
| `(240)` | web/low | ~17 |

```
Briana Banks - WTW16 AIE (1080).mp4
Nikki Benz - Jules Jordan - 4K (2160).mp4
```

If the resolution is genuinely unknown, omit the suffix rather than guessing.

---

## 4. Scene description

The description is a short, human‑readable label for the scene. Derive it from,
in order of preference:

1. The scene `title` in Stash.
2. The `movies[].movieName` plus scene number, for DVD/movie rips
   (`Movie Name - Scene 4`, or the underscored form `Movie_Name_Scene_4`).
3. A concise phrase built from the scene's `tags[]` (e.g. `Hairy Pussy Anal`
   from tags `Anal Sex`, `Hairy Pussy`).

Examples:

```
Mason Storm - Chasing Reality (2004) - Scene 4 (1080).mp4   # movie + year + scene
Mia Rose - Flesh_Hunter_10_Scene_6.mp4                       # DVD rip, underscored
Sheridan Lee - Butt Cream Pie 3 - Hairy Pussy Anal (480).mp4 # movie + tags
Olga Cabaeva - Brunette MILF is giving him a strong blowjob (1080).mp4
```

### Description formatting

- Use spaces for natural‑language descriptions.
- Underscores are acceptable (and traditional) for DVD‑rip scene codes:
  `Flesh_Hunter_10_Scene_6`. Pick one style per scene and stay consistent; do
  not mix within a single filename.
- Keep the year with the movie title in parentheses, e.g.
  `Chasing Reality (2004) - Scene 4`. A year in parentheses is **not** a
  resolution — it stays with the description, and the resolution suffix still
  goes at the end: `... Scene 4 (1080).mp4`.

### Optional inline markers

Square‑bracketed markers may be appended to the description to flag special
status:

| Marker | Meaning | Example |
|--------|---------|---------|
| `[Solo]` | Solo / single‑performer scene | `Teen- Cali Skye - Bald Cunt Model [Solo].mp4` |
| `[4K]` | 4K source (in addition to resolution) | `Sheridan Love - School Teacher [4K] (1440).mp4` |
| `[Incomplete]` | Partial file / missing content | `Sheridan Love - Scores - Action Figure Doll [Incomplete] (720).mp4` |

---

## 5. Separator and character rules

- **Field separator:** ` - ` (space, hyphen, space) between every field.
- **No leading/trailing spaces** in individual fields.
- **Performer names:** use the canonical Stash spelling exactly as it appears in
  `exports/performers.json` (including capitalisation). Do not invent
  spellings; the Stash DB is the source of truth. Note that the DB currently
  contains some lower‑case / misspelled entries (e.g. `naomi woods`,
  `tom byon`) — these should be corrected in Stash, not in the filename.
- **Studio names:** use the canonical Stash studio name from
  `exports/studios.json`. Prefer the short brand name over a URL
  (e.g. `Brazzers`, not `brazzers.com`).
- **Disambiguation:** if two performers share a name, include the Stash
  `disambiguation` in parentheses, e.g. `Sheridan Leigh (UK)`.
- **Aliases:** always use the primary `name`, never an `alias_list` entry.
- **Forbidden characters in filenames:** `/ \ : * ? " < > |`. Replace with a
  space or omit. Apostrophes are allowed (e.g. `Olivia O'Lovely`).
- **Extension:** preserve the original container extension (`.mp4`, `.wmv`,
  `.avi`, ...). Do not transcode as part of renaming.

---

## 6. Data sources (where the names come from)

All performer and studio strings are derived from the Stash database, exported
into this repo:

| File | Contains | GraphQL source |
|------|----------|----------------|
| `exports/performers.json` | `data.allPerformers[]` with `name`, `disambiguation`, `gender`, `alias_list`, `stash_ids` | `allPerformers` |
| `exports/studios.json` | `data.allStudios[]` with `name`, `url`, `aliases`, `stash_ids` | `allStudios` |
| `exports/scenes/*.json` | Per‑scene curated metadata: `studio`, `performers[]`, `movies[].movieName`, `tags[]`, `files[]` | Stash full export (covers stripped) |
| `exports/tags.json` | Tag definitions | `allTags` |

A scene JSON that drives a rename looks like:

```json
{
  "studio": "Plumper Pass",
  "performers": ["Zoey Andrews"],
  "files": ["\\\\192.168.0.31\\Collection\\Video\\Zoey Andrews - Plumper Pass (720).mp4"]
}
```

The `studio` field is present on ~6,100 of ~15,200 scenes; when absent, omit the
studio slot. The `performers[]` array drives the leading performer slot(s).

---

## 7. The Unfiled queue and the eporner source format

Files awaiting rename live in `\\192.168.0.31\Collection\Unfiled\`. The current
batch (~1,655 files) all arrive from eporner in the form:

```
EPORNER.COM - [<12-char ID>] <source description> (<resolution>).mp4
```

Examples:

```
EPORNER.COM - [fwRebEXPh6R] Big Tit Milf Stacie Starr Gets Anal Facial (1080).mp4
EPORNER.COM - [LeTp8qSXudw] TUSHYRAW She Needed A Huge Hard Cock To Gape Her Tight Asshole (1080).mp4
EPORNER.COM - [V6pnudZLeZt] Sabrina Suzuki (720).mp4
```

### Transformation to the convention

1. **Drop** the `EPORNER.COM - [<ID>] ` prefix entirely. The bracketed ID is the
   eporner video ID; it is not part of our identity and is already captured by
   Stash fingerprints/`stash_ids` if needed.
2. **Identify the performer(s)** by matching the scene against Stash (via
   `stash_ids`, the source URL, or auto‑tag). Take the canonical names from
   `exports/performers.json`.
3. **Identify the studio** if one is credited (e.g. `TUSHYRAW` → studio
   `Tushy Raw`). Take the canonical name from `exports/studios.json`.
4. **Build the description** from the remaining source text, cleaned up: remove
   studio brand prefixes that are now in the studio slot, fix casing, drop
   spammy tokens.
5. **Keep the resolution suffix** from the source filename.
6. **Assemble** per §1 and move the file from `Unfiled\` into `Video\`.

### Worked examples

| Source (Unfiled) | Renamed (Video) |
|------------------|-----------------|
| `EPORNER.COM - [fwRebEXPh6R] Big Tit Milf Stacie Starr Gets Anal Facial (1080).mp4` | `Stacie Starr - Big Tit Milf Gets Anal Facial (1080).mp4` |
| `EPORNER.COM - [LeTp8qSXudw] TUSHYRAW She Needed A Huge Hard Cock To Gape Her Tight Asshole (1080).mp4` | `<Performer> - Tushy Raw - She Needed A Huge Hard Cock To Gape Her Tight Asshole (1080).mp4` |
| `EPORNER.COM - [V6pnudZLeZt] Sabrina Suzuki (720).mp4` | `Sabrina Suzuki (720).mp4` |
| `EPORNER.COM - [kBeoHjIctvv] BRAZU Dand@ra Mor@es M1LF (1080).mp4` | `Dandara Moraes - Brazu - MILF (1080).mp4` |

(Performer names in angle brackets must be resolved from Stash before renaming.)

---

## 8. Edge cases and rules of thumb

- **Unknown performer:** lead with the studio (Mode C) or, if neither is known,
  a category (Mode B). Never invent a performer name.
- **Unknown studio:** omit the studio slot entirely. Do not leave an empty
  ` - ` segment.
- **Scene already matches a Stash `movie`:** use the movie name as the
  description root, optionally with ` - Scene N`.
- **Compilation / anthology:** use the `Compilation` category prefix and the
  series/studio as the second slot.
- **Trans content:** use the `TS` category prefix (Mode B) or file under the
  `Video\TS\` subfolder; keep the rest of the pattern identical.
- **Performer‑specific subfolders:** a small number of high‑volume performers
  have dedicated subfolders under `Video\` (e.g. `Video\Max Hardcore\`). Files
  for those performers live in the subfolder and still follow the filename
  pattern above; the subfolder is an organisational layer, not a substitute for
  the performer name in the filename.
- **Don't re‑encode.** Renaming is a metadata operation only.

---

## 9. Quick reference

```
Performer1 - Performer2 - Studio - Description (resolution).ext
```

- Separator everywhere: ` - `
- Performer names: canonical, from `exports/performers.json`
- Studio: canonical, from `exports/studios.json`, omitted if unknown
- Description: from scene title / movie / tags
- Resolution: `(1080)` etc., before the extension, omitted if unknown
- Drop `EPORNER.COM - [ID]` prefixes from Unfiled sources
- Forbidden filename chars: `/ \ : * ? " < > |`
