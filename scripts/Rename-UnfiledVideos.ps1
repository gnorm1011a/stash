# =============================================================================
# Rename-UnfiledVideos.ps1  v2
# =============================================================================
# Proposes new filenames for video files in the Unfiled queue, renaming them
# to match the collection's naming convention.
#
# APPROACH (v2):
#   Rule-based cleanup + intelligent name detection.
#   Does NOT rely on Stash DB matching by default.
#   Uses heuristics to detect performer names from the filename itself.
#
# Convention (derived from Collection\Video archive analysis):
#
#   <LeadToken> - [Subcategory] - [UI] - [Performer(s)] - [Studio] - <Description> (<res>).<ext>
#
#   LeadToken  : Euro | Teen | Asian | Russian | Compilation | Amateur |
#                 Black | Latina | Brazilian | German | TS | UI
#   Subcategory: JAV | Chinese | Thai | Korean  (only after Asian)
#   UI         : inserted when no performer is identified
#
# See NAMING-CONVENTION.md for the full specification.
#
# By default this runs in DRY-RUN mode: it produces a CSV report AND a
# formatted Excel spreadsheet for review, but does not rename anything.
# Pass -Execute to perform the renames.
#
# Usage:
#   .\Rename-UnfiledVideos.ps1                              # dry run, full report
#   .\Rename-UnfiledVideos.ps1 -MinConfidence High          # dry run, high-only
#   .\Rename-UnfiledVideos.ps1 -Execute -MinConfidence High # rename high-only
#   .\Rename-UnfiledVideos.ps1 -SourceFilter 'eporner'      # only eporner files
#   .\Rename-UnfiledVideos.ps1 -NoExcel                     # skip Excel generation
#   .\Rename-UnfiledVideos.ps1 -SampleSize 100              # only process 100 files
#
# =============================================================================

[CmdletBinding()]
param(
    [string]$UnfiledDir   = "\\192.168.0.31\Collection\Unfiled",
    [string]$VideoDir     = "\\192.168.0.31\Collection\Video",
    [string]$OutputPath   = "",
    [string]$SourceFilter = "eporner",
    [ValidateSet("High","Medium","Low","None")]
    [string]$MinConfidence = "None",
    [int]$SampleSize = 0,           # 0 = process all
    [switch]$Execute,
    [switch]$NoExcel
)

# Resolve defaults relative to script location (handles UNC paths)
if (-not $OutputPath) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $exportsDir = (Resolve-Path (Join-Path $scriptDir "..\exports")).Path
    $OutputPath = Join-Path $exportsDir "unfiled-rename-plan.csv"
}

$ErrorActionPreference = "Stop"

function Write-Step { param([string]$msg) Write-Host "[Rename] $msg" -ForegroundColor Cyan }
function Write-Ok   { param([string]$msg) Write-Host "  OK: $msg" -ForegroundColor Green }
function Write-Warn { param([string]$msg) Write-Host "  WARN: $msg" -ForegroundColor Yellow }
function Write-Err  { param([string]$msg) Write-Host "  ERROR: $msg" -ForegroundColor Red }

# =============================================================================
# Configuration
# =============================================================================

# -----------------------------------------------------------------------------
# Valid lead tokens (ONLY these — derived from Collection\Video archive)
# -----------------------------------------------------------------------------
# Category lead tokens (Mode B)
#   Euro, Teen, Asian, Russian, Compilation, Amateur, Black, Latina, Brazilian, German, TS
# Studio lead tokens (Mode C) — studios that lead directly
#   BRCC, Hookup Hotshot, Facial Abuse, Scores, 2 Drops
# UI — fallback when nothing else is identified

# -----------------------------------------------------------------------------
# Category keyword mappings
# Maps keywords found in the description to (LeadToken, Subcategory)
# -----------------------------------------------------------------------------
# Asian convention: Japanese → Asian - JAV, Chinese → Asian - Chinese, etc.
$asianKeywords = [ordered]@{
    'japanese'   = @{ Lead = 'Asian'; Sub = 'JAV' }
    'jav'        = @{ Lead = 'Asian'; Sub = 'JAV' }
    'chinese'    = @{ Lead = 'Asian'; Sub = 'Chinese' }
    'thai'       = @{ Lead = 'Asian'; Sub = 'Thai' }
    'korean'     = @{ Lead = 'Asian'; Sub = 'Korean' }
    'vietnamese' = @{ Lead = 'Asian'; Sub = 'Asian' }
    'filipino'   = @{ Lead = 'Asian'; Sub = 'Asian' }
    'asian'      = @{ Lead = 'Asian'; Sub = '' }
}

# Euro convention: French, Italian, Czech, etc. → Euro
$euroKeywords = @(
    'french','italian','czech','hungarian','polish','spanish','portuguese',
    'swedish','norwegian','danish','finnish','dutch','belgian','austrian',
    'swiss','greek','turkish','irish','scottish','welsh','icelandic',
    'romanian','bulgarian','serbian','croatian','slovak','slovenian',
    'ukrainian','euro','european'
)

# Direct nationality → lead token
$nationalityKeywords = [ordered]@{
    'russian'    = 'Russian'
    'german'     = 'German'
    'brazilian'  = 'Brazilian'
    'brasil'     = 'Brazilian'
    'brasilian'  = 'Brazilian'
    'latina'     = 'Latina'
    'latin'      = 'Latina'
    'colombian'  = 'Latina'
    'mexican'    = 'Latina'
    'cuban'      = 'Latina'
    'argentinian'= 'Latina'
    'venezuelan' = 'Latina'
    'peruvian'   = 'Latina'
    'ebony'      = 'Black'
}

# Black is handled separately because "black" can be a color adjective
# (e.g. "Black Skirt") not just an ethnicity indicator.
# Only detect Black as lead token when NOT followed by a clothing item.
$blackClothingPattern = '\bblack\s+(skirt|dress|shirt|pants|jeans|jacket|coat|sweater|lingerie|bikini|stockings|heels|shoes|boots|hat|cap|scarf|gloves|belt|tie|bra|panties|thong|garter|fishnet|leather|latex|rubber|silk|satin|lace|corset|robe|nightgown|negligee|babydoll|teddy|body|suit|blouse|top|skirt|miniskirt)\b'

# TS convention: tgirl, shemale, trans → TS
# Note: "ts" is only 2 chars but \b word boundary prevents matching inside other words
$tsKeywords = @('tgirl','tsgirl','shemale','trans','transgender','tranny','transsexual','ladyboy','ts')

# Teen indicators (careful — only match as whole words, not inside other words)
$teenKeywords = @('teen','18yo','19yo','18 yo','19 yo','18-year','19-year')

# Amateur indicators
$amateurKeywords = @('amateur','homemade','home video','home made')

# Compilation indicators
$compilationKeywords = @('compilation','compilations','best of','mega pack','megapack')

# -----------------------------------------------------------------------------
# Known studios with special handling
# -----------------------------------------------------------------------------
# Studios that LEAD directly (Mode C)
$leadStudios = [ordered]@{
    'brcc'             = 'BRCC'
    'backroom casting' = 'BRCC'
    'hookup hotshot'   = 'Hookup Hotshot'
    'facial abuse'     = 'Facial Abuse'
    'scores'           = 'Scores'
    '2 drops'          = '2 Drops'
    '2drops'           = '2 Drops'
}

# Studios that require a category prefix (e.g. TTL → Teen - TTL)
$prefixedStudios = [ordered]@{
    'ttl'         = @{ Prefix = 'Teen'; Studio = 'TTL' }
    'ttlv'        = @{ Prefix = 'Teen'; Studio = 'TTL' }
    'showy beauty'= @{ Prefix = 'Teen'; Studio = 'Showy Beauty' }
    'showybeauty' = @{ Prefix = 'Teen'; Studio = 'Showy Beauty' }
    'show beauty' = @{ Prefix = 'Teen'; Studio = 'Showy Beauty' }
    'sb'          = @{ Prefix = 'Teen'; Studio = 'Showy Beauty' }
    'asian street meat' = @{ Prefix = 'Asian'; Studio = 'Asian Street Meat' }
    'asm'         = @{ Prefix = 'Asian'; Studio = 'Asian Street Meat' }
    'street meat' = @{ Prefix = 'Asian'; Studio = 'Asian Street Meat' }
    'assman'      = @{ Prefix = 'Euro'; Studio = 'Assman' }
    'brazu'       = @{ Prefix = 'Brazilian'; Studio = 'BRAZU' }
}

# Secondary studios (identified but don't lead — placed after performer/UI)
$secondaryStudios = [ordered]@{
    'tushy raw'   = 'Tushy Raw'
    'tushyraw'    = 'Tushy Raw'
    'tushy'       = 'Tushy'
    'vixen'       = 'Vixen'
    'blacked'     = 'Blacked'
    'blackedraw'  = 'Blacked Raw'
    'blacked raw' = 'Blacked Raw'
    'deeper'      = 'Deeper'
    'true anal'   = 'True Anal'
    'trueanal'    = 'True Anal'
    'all anal'    = 'All Anal'
    'allanal'     = 'All Anal'
    'anal only'   = 'Anal Only'
    'analonly'    = 'Anal Only'
    'ass traffic' = 'Ass Traffic'
    'assman'      = 'Assman'
    'hard brazil' = 'Hard Brazil'
    'hardbrazil'  = 'Hard Brazil'
    'mom pov'     = 'MomPOV'
    'mompov'      = 'MomPOV'
    'gloryhole secrets' = 'Gloryhole Secrets'
    'gloryhole'   = 'Gloryhole Secrets'
    'step1models' = 'Step1Models'
    'step 1 models' = 'Step1Models'
    'cosmid'      = 'Cosmid'
    'ddf'         = 'DDF'
    'wicked pictures' = 'Wicked Pictures'
    'wicked'      = 'Wicked Pictures'
    'elegant angel' = 'Elegant Angel'
    'brazzers'    = 'Brazzers'
    'naughty america' = 'Naughty America'
    'reality kings' = 'Reality Kings'
    'bangbros'    = 'BangBros'
    'bang bros'   = 'BangBros'
    'mofos'       = 'Mofos'
    'team skeet'  = 'Team Skeet'
    'teamskeet'   = 'Team Skeet'
    'jules jordan' = 'Jules Jordan'
    'evil angel'  = 'Evil Angel'
    'digital playground' = 'Digital Playground'
    'private'     = 'Private'
    'hustler'     = 'Hustler'
    'penthouse'   = 'Penthouse'
    'playboy'     = 'Playboy'
    'bbtg'        = 'BBTG'
    'trans500'    = 'Trans500'
    'dream tranny' = 'Dream Tranny'
    'dreamtranny' = 'Dream Tranny'
}

# -----------------------------------------------------------------------------
# Reviewer corrections from v1 review (155 notes in Google Sheet)
# Maps eporner IDs to specific performer names that the heuristic detector
# misses, or to complete filename overrides.
# -----------------------------------------------------------------------------

# Performer corrections: eporner ID → array of performer names
# These are names the reviewer identified that the heuristic detector misses
$performerCorrections = @{
    'W1yyjxOABcN' = @('Amber Alena')           # "AmberA" → Amber Alena
    'fwRebEXPh6R' = @('Stacie Starr')           # confirmed
    'kBeoHjIctvv' = @('Dandara Moraes')         # obfuscated
    'IoBXuSatrYP' = @('Chantal Danielle')       # missed
    'liulyMb4kzM' = @('Sybil Stallion')         # missed
    'aAuzkflWzZS' = @('Amaya May')              # missed
    '3DWA95xI5ON' = @('Kiyoko Ida')             # missed
    'xIGrUd0Qqvx' = @('Lara Lima')              # missed
    'YmuxER9IgDL' = @('Hayley Davies')          # missed
    'Deq3jL0UEc9' = @('Trudy Doll')             # missed
    'B1wbNbSIpzT' = @('Akame Reiran')           # missed
    'yCYlNm75nY8' = @('Meiko A')                # missed (note: keeps the A.)
    'aGhShDb8Fzd' = @('Sindy')                  # missed (single word)
    'o9eq0tCox7F' = @('Rhea Radford')           # Hookup Hotshot
    'VB6mzqgjX6w' = @('Momoka Kagura')          # missed
    'JAfRt9CokP4' = @('Mila Vega')              # missed
    'bY9GF8NrIP7' = @('Himari Konshita')        # missed
    '17VsXV5L39w' = @('Kalliny Nomura')         # missed (TS)
    'EcAlwklVpL4' = @('Hitomi')                 # single word, needs Asian-JAV
    'pORWhg79g4s' = @('Mizuki')                 # single word
    'I7HmIyh6vjh' = @('Giovanna Martinelly')    # missed
    'Tiv6aiShd8i' = @('Monika Fox','Shalinia')  # multiple performers
    'iIBTNpaRBG4' = @('Kaitlyn Moore')          # missed
    'cMwMsLMSYDW' = @('Samantha Blaze')         # spelling correction
    'JhG1NXHF1lJ' = @('Amaya May')              # missed
    'w9FbkOAxc24' = @('Vicky Chase')            # missed
    'pbiwHgdhcUD' = @('Naomi Bennet')           # missed
    'itqGC4FEr0r' = @('Sophie Stephan')         # missed
    'oEwtfTSVL3M' = @('Denisse Naima')          # TS, missed
    'Y5nJywwJiOu' = @('Davina Winter')          # missed
    'XJJovNizAWO' = @('Cassia Carvalho')        # TS, missed
    'lJx31IrXt8M' = @('Chantell Fox')           # missed
    'MOVUynJC6K2' = @('Chantelle Fox')          # missed (alt spelling)
    'hI8iXgKiSej' = @('Courtney Love')          # from Courtney_Luv
    'NJiV8KuBKHy' = @('Chloe Cherry')           # from ChloeCherry
    '44qkMHqmufO' = @('Ericka Locket')          # missed
    'qLOIBRtfHyw' = @('Angelina Elise')         # missed
    'yow4eOii4hu' = @('Anna Vlasova','Alissa')  # multiple
    'P7B50BmaEeA' = @('Victoria Voxxx')         # missed
    '0FEffWUWmza' = @('Mariana Torres','Ma Santos')  # multiple
    '8CPeij0Bws8' = @('Starr Power')            # missed
    'jiEeFv75gVT' = @('Lika Zolotce','Mr. Henderson')  # female first
    'AziEtpHypJO' = @('Emmanuelle Worley')      # missed
    '6YYe6OsHR8C' = @('Elle Devyne')            # missed
    'laWF7dZ2DXV' = @('Luna Baiana')            # missed
    'zBYBG1rx9kc' = @('Popsy')                  # single word
    '5f7JrD7RXnm' = @('Abbey Rain')             # missed
    'cOmayEXM0iG' = @('Jasmin Lotus')           # TS, missed (was filtered as studio)
    'RowScUoOeYj' = @('Britany Mazo')           # TTL, missed
    'qPF9VSYBScc' = @('Brittany Mazo')          # TTL, missed
    'YYO2u8bdUc6' = @('Brittany Mazo')          # TTL, missed
    'jRmzoShe8cj' = @('Angel Rain')             # missed
    'B3f5zYQeRn7' = @('Momoka')                 # single word
    'HDQvnrTh26X' = @('Tessa Violet')           # Gloryhole Secrets
    'lOwy2aB9DRF' = @('Athena Rose')            # missed
    'SQerFs2281e' = @('Celine')                 # single word, Euro
    'MDedzDeCJ7h' = @('Isabella Jessica')       # missed
    'aCgkWuBShbV' = @('Jelica')                 # missed
    'Ei1fll4xyA3' = @('Marilyn Sugar')          # missed
    'bYTF1kgoMd0' = @('Lexi Lockhart')          # missed
    '3Wz33zkANje' = @('Renata Silva','Mary Torres')  # multiple
    'vPrUyVNE8GV' = @('Chloe Delaure')          # missed
    'tfAz5GFxw88' = @('Violet Myers')           # from Violet.Myers
    'e6wf1CEyN7c' = @('Klisex','Alecia Fox')    # multiple
    'JGEvSgweuwY' = @('Julie Skyhigh')          # missed
    'lY0VXMVPHqZ' = @("Brittany O'Neil")        # spelling correction
    'mC0CyBqqXQC' = @('Rachel Boost')           # missed
    'nXyPOaUely5' = @('Ariel Demure','Angelina Please','Jenna Creed')  # TS, multiple
    'ymLXWbbCCTM' = @('Karen Kay')              # missed
    'ApX7m0VgUWf' = @('Janice Griffith')        # missed
    'pXoY1BzoF92' = @('Betty Carr')             # missed
    '3OnV6oBuGDI' = @('Kayla Carrera')          # missed
    'W1fYpk9VwR1' = @('Gabi Souza')             # missed
    'NVpzmEVSJ9r' = @('Nia Nacci')              # missed
    '0CjgK0yZ8qx' = @('Kathy Heart')            # missed
    'h7afsGFwo60' = @('Adrianna Wild','Starr Blue')  # multiple
    'bnCkqTpnLMA' = @('Spencer Bradley')        # missed
    'kB3tHFAYSMw' = @()                         # performer not specified
    'pf4uqiiZGTT' = @('Hitomi Tanaka')          # confirmed, needs Asian-JAV
    'suS6kaC4hgi' = @('Alexa Blun')             # needs Latina lead
    'gbSiq5Fd2kL' = @('Yumi Sin')               # confirmed
    '5vgxwomUcMX' = @()                         # needs Asian lead, no performer
    'ji4ydcJFkyo' = @()                         # needs Asian-JAV lead
    '15mZF7lND8i' = @()                         # needs Asian-JAV lead
    'LBPcjm79wGB' = @()                         # needs Asian-JAV lead
    '5Eb6l01Xc8J' = @()                         # needs Asian-JAV-UI
    'WgXvftCAdqK' = @()                         # needs Asian-JAV-UI
    '4P8CHrCri7U' = @()                         # Teen - Show Beauty - UI
}

# Lead token corrections: eporner ID → @{ Lead='...'; Sub='...'; Studio='...' }
# For cases where the lead token detection was wrong
$leadTokenCorrections = @{
    'pf4uqiiZGTT' = @{ Lead='Asian'; Sub='JAV' }   # Hitomi Tanaka
    '3DWA95xI5ON' = @{ Lead='Asian'; Sub='JAV' }   # Kiyoko Ida
    'suS6kaC4hgi' = @{ Lead='Latina'; Sub='' }     # Alexa Blun
    '5vgxwomUcMX' = @{ Lead='Asian'; Sub='' }      # Asian content
    'gbSiq5Fd2kL' = @{ Lead='Asian'; Sub='JAV' }   # Yumi Sin
    'ji4ydcJFkyo' = @{ Lead='Asian'; Sub='JAV' }   # Asian content
    '15mZF7lND8i' = @{ Lead='Asian'; Sub='JAV' }   # Asian content
    'LBPcjm79wGB' = @{ Lead='Asian'; Sub='JAV' }   # Asian content
    '5Eb6l01Xc8J' = @{ Lead='Asian'; Sub='JAV' }   # Shaved Japanese Mom
    'WgXvftCAdqK' = @{ Lead='Asian'; Sub='JAV' }   # Busty Japanese chick
    'yCYlNm75nY8' = @{ Lead='Asian'; Sub='JAV' }   # Meiko A.
    'VB6mzqgjX6w' = @{ Lead='Asian'; Sub='JAV' }   # Momoka Kagura
    'bY9GF8NrIP7' = @{ Lead='Asian'; Sub='JAV' }   # Himari Konshita
    'EcAlwklVpL4' = @{ Lead='Asian'; Sub='JAV' }   # Hitomi
    'pORWhg79g4s' = @{ Lead='Asian'; Sub='JAV' }   # Mizuki
    'B3f5zYQeRn7' = @{ Lead='Asian'; Sub='JAV' }   # Momoka
    'OHhdeLZ8WQl' = @{ Lead='German'; Sub='' }     # German content
    'rmO3KWcL20I' = @{ Lead='German'; Sub='' }     # German content
    'jUL3OAJr7Wr' = @{ Lead='Latina'; Sub='' }     # Latina content
    'ncix6sf4r4N' = @{ Lead='Brazilian'; Sub='' }  # Brazilian content
    'DjuG3Zso5E2' = @{ Lead='Brazilian'; Sub='' }  # Brazilian content
    'C8xu0dT5afd' = @{ Lead='Brazilian'; Sub='' }  # Brazilian, not Brasil
    'I7HmIyh6vjh' = @{ Lead='Brazilian'; Sub='' }  # Giovanna Martinelly
    'bfB5urAlyYh' = @{ Lead='Brazilian'; Sub='' }  # Mirelle Sanchez
    'PsjINWJ4FEV' = @{ Lead='Brazilian'; Sub='' }  # May Fujita
    'laWF7dZ2DXV' = @{ Lead='Brazilian'; Sub='' }  # Luna Baiana
    '3Wz33zkANje' = @{ Lead='Brazilian'; Sub='' }  # Renata Silva - Mary Torres
    'JAfRt9CokP4' = @{ Lead='Latina'; Sub='' }     # Mila Vega - Colombian
    'oEwtfTSVL3M' = @{ Lead='TS'; Sub='' }         # Denisse Naima
    'XJJovNizAWO' = @{ Lead='TS'; Sub='' }         # Cassia Carvalho
    'cOmayEXM0iG' = @{ Lead='TS'; Sub='' }         # Jasmin Lotus
    '17VsXV5L39w' = @{ Lead='TS'; Sub='' }         # Kalliny Nomura
    'nXyPOaUely5' = @{ Lead='TS'; Sub='' }         # Ariel Demure - Angelina Please - Jenna Creed
    'jmmixNBiVjL' = @{ Lead='TS'; Sub='' }         # Tgirl/shemale/trans
    'BRG9dEQd3yw' = @{ Lead='MomPOV'; Sub='' }     # MomPOV as lead
    'dL1AyLDCM9I' = @{ Lead='Hookup Hotshot'; Sub='' }  # Hookup Hotshot
    'o9eq0tCox7F' = @{ Lead='Hookup Hotshot'; Sub='' }  # Hookup Hotshot - Rhea Radford
    # TTL cases → Teen lead
    '42NrbrVOmWX' = @{ Lead='Teen'; Sub='' }       # Teen - TTL
    'RowScUoOeYj' = @{ Lead='Teen'; Sub='' }       # Teen - TTL - Britany Mazo
    'qPF9VSYBScc' = @{ Lead='Teen'; Sub='' }       # Teen - TTL - Brittany Mazo
    'YYO2u8bdUc6' = @{ Lead='Teen'; Sub='' }       # Teen - TTL - Brittany Mazo
    'AnPwVsvPkRU' = @{ Lead='Teen'; Sub='' }       # Teen - TTL - Yeraldin
    # Showy Beauty → Teen lead
    'UQ8FTAnIHH7' = @{ Lead='Teen'; Sub='' }       # Teen - Show Beauty
    '4P8CHrCri7U' = @{ Lead='Teen'; Sub='' }       # Teen - Show Beauty
    # Hard Brazil → Brazilian lead
    'mTp85UDfrnh' = @{ Lead='Brazilian'; Sub='' }  # Brazilian - Hard Brazil
    # Celine → Euro lead (not Asian)
    'SQerFs2281e' = @{ Lead='Euro'; Sub='' }       # Euro - Celine
    # Assman → Euro lead
    'QgMYLLxldF7' = @{ Lead='Euro'; Sub='' }       # Euro - Assman
    'ul0kkySaAN2' = @{ Lead='Euro'; Sub='' }       # Euro - Assman
    'HutpqyYaMe5' = @{ Lead='Euro'; Sub='' }       # Euro - Assman
    'PjEPQlinJLH' = @{ Lead='Euro'; Sub='' }       # Euro - Assman
}

# Studio corrections: eporner ID → studio name
$studioCorrections = @{
    'dL1AyLDCM9I' = 'Hookup Hotshot'
    'o9eq0tCox7F' = 'Hookup Hotshot'
    'BRG9dEQd3yw' = 'MomPOV'
    'b6g3tg318Jk' = 'MomPOV'
    'HDQvnrTh26X' = 'Gloryhole Secrets'
    'mTp85UDfrnh' = 'Hard Brazil'
    'QgMYLLxldF7' = 'Assman'
    'ul0kkySaAN2' = 'Assman'
    'HutpqyYaMe5' = 'Assman'
    'PjEPQlinJLH' = 'Assman'
    '42NrbrVOmWX' = 'TTL'
    'RowScUoOeYj' = 'TTL'
    'qPF9VSYBScc' = 'TTL'
    'YYO2u8bdUc6' = 'TTL'
    'AnPwVsvPkRU' = 'TTL'
    'UQ8FTAnIHH7' = 'Showy Beauty'
    '4P8CHrCri7U' = 'Showy Beauty'
    'md4FWIP491k' = 'Asian Street Meat'
}

# -----------------------------------------------------------------------------
# Acronyms that should ALWAYS be ALL CAPS
# -----------------------------------------------------------------------------
$acronyms = @(
    'MILF','GILF','BBW','POV','TS','JAV','UI','BBC','BWC','IR','DP','ATM','ATP',
    'BGA','BWA','BWB','BWC','BRCC','TTL','TTLV','BBTG','DDF','HD','SD','VR',
    'AI','FPS','FFM','MMF','FMM','BJ','HJ','IR','PAWG','ASM','SB','4K','8K'
)

# Build a regex pattern for acronym matching (longest first)
$acronymPattern = ($acronyms | Sort-Object { $_.Length } -Descending | ForEach-Object { [regex]::Escape($_) }) -join '|'
$acronymRegex = [regex]::new("\b($acronymPattern)\b", [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)

# -----------------------------------------------------------------------------
# Non-name words — capitalized words that are NOT performer names
# Used by the heuristic name detector to filter false positives
# -----------------------------------------------------------------------------
$nonNameWords = [System.Collections.Generic.HashSet[string]]::new(
    [string[]]@(
        # Size descriptors
        'Big','Small','Petite','Tall','Short','Thick','Thin','Huge','Massive',
        'Giant','Tiny','Little','Large','Round','Super','Very'
        # Age descriptors
        'Young','Old','New','Teen','Mature','MILF','Granny','Cougar','GILF'
        # Body descriptors
        'Busty','Hairy','Shaved','Curvy','Chubby','Slim','Skinny','Fat','Fit',
        'Muscular','BBW','PAWG','Inked','Tattooed','Pierced','Natural','Fake',
        'Silicone','Bimbo','Bold','Bald','Naked','Nude','Topless','Bottomless'
        # Hair color
        'Blonde','Brunette','Redhead','Brown','Grey','Gray','Black','White'
        # Action words
        'Gets','Got','Fucked','Fucking','Fucks','Sucks','Sucking','Suck',
        'Licks','Licking','Lick','Eats','Eating','Eat','Pounded','Drilled',
        'Banged','Plowed','Ravaged','Destroyed','Stuffed','Filled','Creampied',
        'Covered','Drenched','Soaked','Wet','Oiled','Oily','Takes','Taking',
        'Giving','Gives','Gave','Loves','Liked','Likes','Wants','Needs',
        'Enjoys','Enjoyed','Shows','Show','Strips','Stripping','Strip',
        'Teases','Teasing','Tease','Poses','Posing','Pose','Dances','Dancing',
        'Dance','Masturbates','Masturbating','Masturbate','Plays','Playing',
        'Play','Rides','Riding','Ride','Mounts','Mounted','Squirts','Squirting',
        'Squirt','Swallows','Swallowing','Swallow','Gags','Gagging','Gag',
        'Deepthroats','Deepthroating','Deepthroat','Spanks','Spanking','Spank'
        # Quality descriptors
        'Hot','Sexy','Beautiful','Gorgeous','Cute','Pretty','Amazing',
        'Awesome','Incredible','Stunning','Lovely','Sweet','Naughty','Horny',
        'Kinky','Filthy','Dirty','Nasty','Wild','Crazy','Insane','Rough',
        'Gentle','Hard','Soft','Tight','Loose','Deep','Shallow','Fresh',
        'Pure','Raw','Intense','Extreme','Sloppy','Messy','Clean'
        # Body parts
        'Tits','Tit','Boobs','Boob','Ass','Butt','Butts','Cock','Cocks',
        'Dick','Dicks','Pussy','Cunt','Nipples','Nipple','Breast','Breasts',
        'Cleavage','Face','Mouth','Tongue','Hands','Hand','Feet','Foot',
        'Legs','Leg','Arms','Arm','Body','Skin','Lips','Hip','Hips','Thigh',
        'Thighs','Belly','Back','Shoulder','Shoulders','Neck','Throat'
        # Categories
        'Anal','Oral','Blowjob','Handjob','Deepthroat','Hardcore','Softcore',
        'Lesbian','Threesome','Foursome','Orgy','Gangbang','Creampie','Facial',
        'Cumshot','Cum','Sperm','Jizz','POV','Solo','Casting','Compilation',
        'Amateur','Homemade','Pro','Professional','IR','BBC','BWC','DP','ATM',
        'ATP','BGA','BWA','BWB','TS','Tgirl','Shemale','Trans','Tranny',
        'Pegging','Fisting','Rimming','Rimjob','Footjob','Tittyfuck'
        # Nationality/Ethnicity
        'Russian','German','Brazilian','Asian','Japanese','Chinese','Thai',
        'Korean','French','Italian','Spanish','Mexican','Cuban','Czech',
        'Swedish','Hungarian','Polish','Ukrainian','Turkish','Indian','Arab',
        'Euro','Latina','Ebony','Colombian','Latin','American','British',
        'Australian','Canadian','Dutch','Belgian','Austrian','Swiss','Greek',
        'Portuguese','Danish','Norwegian','Finnish','Icelandic','Irish',
        'Scottish','Welsh','Romanian','Bulgarian','Serbian','Croatian',
        'Slovak','Slovenian','European','Brasil','Brasilian'
        # Common English words
        'With','And','The','A','An','In','On','At','By','For','To','Of',
        'From','Is','Was','Has','Had','Being','While','When','After',
        'Before','During','First','Second','Third','One','Two','Three',
        'Four','Five','Six','Seven','Eight','Nine','Ten','Her','His',
        'Their','She','He','They','It','This','That','These','Those','My',
        'Your','Our','Its','Or','But','Not','No','Yes','So','If','Then',
        'Than','Also','Just','Only','Even','Still','Yet','Now','Here',
        'There','Who','Whom','Whose','Which','What','Where','Why','How',
        'All','Each','Every','Both','Either','Neither','None','Some','Any',
        # Porn-specific terms
        'Whore','Slut','Bitch','Mistress','Goddess','Queen','King',
        'Princess','Baby','Babe','Girl','Girls','Boy','Boys','Man','Men',
        'Woman','Women','Lady','Ladies','Guy','Guys','Dude','Mom','Moms',
        'Dad','Dads','Mother','Father','Sister','Brother','Daughter','Son',
        'Wife','Wives','Husband','Girlfriend','Boyfriend','Friend','Friends',
        'Neighbor','Neighbors','Stranger','Strangers','Boss','Employee',
        'Teacher','Student','Doctor','Nurse','Secretary','Maid','Nanny',
        'Babysitter','Stepdad','Stepmom','Stepson','Stepdaughter','Step',
        # Media terms
        'Video','Scene','Part','Episode','Chapter','Volume','Version',
        'Clip','Movie','Film','Audio','HD','SD','K','P','FPS','AI',
        'Enhanced','Upscaled','Uncensored','Censored','Mosaic','Removed',
        'Original','Copy','Edit','Edited','Remastered','Restored',
        # Other
        'Iron','Action','Adventure','Story','Stories','Tale','Tales',
        'Secret','Secrets','Private','Public','Best','Worst','Good','Bad',
        'Great','Perfect','Real','Fake','True','False','Right','Wrong',
        'Top','Bottom','Side','Front','Back','Left','Right','Up','Down',
        'Inside','Outside','Indoor','Outdoor','Bedroom','Bathroom','Kitchen',
        'Living','Office','Classroom','Gym','Pool','Beach','Outdoor','Car',
        'Hotel','Motel','Room','Shower','Bath','Bed','Couch','Sofa','Floor',
        'Table','Desk','Chair','Counter','Wall','Window','Door','Closet',
        'Basement','Attic','Garage','Yard','Garden','Park','Street','Road',
        'City','Town','Village','Country','World','Earth','Planet','Space',
        # Additional non-name words (from v2 testing false positives)
        'Hundred','Ninety','Eight','Eighty','Fifty','Forty','Thirty','Twenty',
        'Ten','Eleven','Twelve','Thirteen','Fourteen','Fifteen','Sixteen',
        'Seventeen','Eighteen','Nineteen','Million','Billion','Thousand',
        'Reincarnated','Hottie','Bimbo','Archive','Dance','Dancing',
        'Skirt','Dress','Shirt','Pants','Jeans','Jacket','Coat','Sweater',
        'Lingerie','Bikini','Stockings','Heels','Shoes','Boots','Hat','Cap',
        'Scarf','Gloves','Belt','Tie','Bra','Panties','Thong','Garter',
        'Fishnet','Leather','Latex','Rubber','Silk','Satin','Lace','Cotton',
        'Sheer','Nude','Pink','Blue','Red','Green','Yellow','Orange',
        'Purple','Silver','Gold','Bronze','Copper','Crimson','Scarlet',
        'Maroon','Burgundy','Emerald','Sapphire','Ivory','Cream','Tan',
        'Banana','Apple','Cherry','Strawberry','Peach','Mango','Coconut',
        'Cream','Pie','Cake','Candy','Sugar','Honey','Chocolate','Vanilla',
        'Pet','Toy','Doll','Puppet','Robot','Machine','Device','Tool',
        'Instrument','Apparatus','Gadget','Gizmo','Contraption',
        'Striptease','Burlesque','Cabaret','Show','Performance','Routine',
        'Audition','Interview','Casting','Tryout','Test','Exam','Check',
        'Anniversary','Birthday','Holiday','Vacation','Weekend','Night',
        'Day','Morning','Evening','Afternoon','Midnight','Noon','Dawn',
        'Dusk','Sunrise','Sunset','Today','Tomorrow','Yesterday',
        'Christmas','Halloween','Thanksgiving','Valentine','Easter',
        'Newyear','New','Year','Years','Time','Times','Moment','Moments',
        'First','Second','Third','Fourth','Fifth','Sixth','Seventh',
        'Eighth','Ninth','Tenth','Last','Final','Next','Previous',
        'Beginning','End','Start','Finish','Middle','Center','Centre',
        'Way','Path','Road','Route','Track','Trail','Course','Direction',
        'Visit','Visitor','Guest','Host','Party','Parties','Celebration',
        'Festival','Carnival','Parade','Fair','Expo','Exhibition','Display',
        'Blast','Bonanza','Extravaganza','Spectacular','Special','Feature',
        'Presentation','Demonstration','Exhibition','Showcase','Premiere',
        'Blw','Bwa','Bwb','Bga','Fbb','Sbb','Bbc','Bwc',
        # Additional from v2 full-run false positives
        'TBF','TTLV','Identical','Twins','Twin','Sisters','Sister',
        'Twins','Double','Triple','Solo','Duo','Trio',
        'Hotshot','Hookup','Casting','Audition',
        'Latn','Latin','Latina','Latino','Ethnic','Exotic'
    ),
    [System.StringComparer]::OrdinalIgnoreCase
)

# -----------------------------------------------------------------------------
# Junk text patterns to remove during cleanup
# -----------------------------------------------------------------------------
# Regex patterns for random strings, hex codes, and known junk text
$junkPatterns = @(
    '\b[0-9A-F]{8,}\b'                          # hex strings 8+ chars
    '\b[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}\b'   # UUID-like patterns
    '\bQTGMC\b.*?(?=\s|$)'                      # QTGMC processing notes
    '\b\d{2,4}\s*fps\b'                         # fps notes
    '\bAI\s*Enhanced\b'                         # AI Enhanced
    '\bAI\s*Upscaled?\b'                        # AI Upscale
    '\bUpscaled?\b'                             # Upscaled
    '\bEnhanced\b'                              # Enhanced
    '\bDGS\b'                                   # DGS watermark
    '\bOB\d{3,}\b'                              # OB### codes
    '\bEPORNER\b'                               # leftover eporner text
    '\bXVIDEOS?\b'                              # xvideos watermark
    '\bXNXX\b'                                  # xnxx watermark
    '\bPORNHUB\b'                               # pornhub watermark
    '\bREDTUBE\b'                               # redtube watermark
    '\bTUBE8\b'                                 # tube8 watermark
    '\bSPANKBANG\b'                             # spankbang watermark
    '\b\d{6,}\b'                                # 6+ digit numbers (likely IDs)
)

# =============================================================================
# Helper Functions
# =============================================================================

# -----------------------------------------------------------------------------
# Parse an eporner filename into its components
# -----------------------------------------------------------------------------
function Parse-EpornerFilename {
    param([string]$Filename)

    $ext = [System.IO.Path]::GetExtension($Filename)
    $base = [System.IO.Path]::GetFileNameWithoutExtension($Filename)

    # Extract eporner ID: EPORNER.COM - [XXXXXXXXXXX] ...
    $idMatch = [regex]::Match($base, '^\s*EPORNER\.COM\s*-\s*\[([^\]]+)\]\s*', [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
    $epornerId = ""
    $desc = $base
    if ($idMatch.Success) {
        $epornerId = $idMatch.Groups[1].Value
        $desc = $base.Substring($idMatch.Length)
    }

    # Extract resolution suffix: (1080), (720), (2160p), 4K, etc.
    $resMatch = [regex]::Match($desc, '\s*[\(\[]?(\d{3,4})p?[\)\]]?\s*$', [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
    $resolution = ""
    if ($resMatch.Success) {
        $resolution = $resMatch.Groups[1].Value
        $desc = $desc.Substring(0, $resMatch.Index).Trim()
    }

    # Also check for 4K/8K resolution markers
    if (-not $resolution) {
        $kMatch = [regex]::Match($desc, '\s*[\(\[]?(4K|8K)[\)\]]?\s*$', [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
        if ($kMatch.Success) {
            $resolution = $kMatch.Groups[1].Value.ToUpper()
            $desc = $desc.Substring(0, $kMatch.Index).Trim()
        }
    }

    return @{
        EpornerID   = $epornerId
        Description = $desc.Trim()
        Resolution  = $resolution
        Extension   = $ext
        Raw         = $Filename
    }
}

# -----------------------------------------------------------------------------
# Normalise obfuscation: @->a, 1->i, 0->o, 3->e, $->s
# Only replaces characters BETWEEN letters to preserve numbers like "1080"
# -----------------------------------------------------------------------------
function Invoke-TextNormalisation {
    param([string]$Text)
    $t = $Text
    $t = $t -replace '(?<=[a-zA-Z])@(?=[a-zA-Z])', 'a'
    $t = $t -replace '(?<=[a-zA-Z])1(?=[a-zA-Z])', 'i'
    $t = $t -replace '(?<=[a-zA-Z])0(?=[a-zA-Z])', 'o'
    $t = $t -replace '(?<=[a-zA-Z])3(?=[a-zA-Z])', 'e'
    $t = $t -replace '(?<=[a-zA-Z])\$(?=[a-zA-Z])', 's'
    # M1LF → MILF (special case: digit 1 between consonants)
    $t = $t -replace '\bM1LF\b', 'MILF'
    $t = $t -replace '\bM1lf\b', 'MILF'
    $t = $t -replace '\bmi1f\b', 'MILF'
    return $t
}

# -----------------------------------------------------------------------------
# Remove junk text patterns from the description
# -----------------------------------------------------------------------------
function Remove-JunkText {
    param([string]$Text)
    $t = $Text
    foreach ($pattern in $junkPatterns) {
        $t = $t -replace $pattern, ''
    }
    # Clean up after removal
    $t = $t -replace '\s{2,}', ' '
    $t = $t.Trim()
    return $t
}

# -----------------------------------------------------------------------------
# Remove formatting artifacts: brackets, braces, underscores, stray punctuation
# -----------------------------------------------------------------------------
function Remove-FormattingArtifacts {
    param([string]$Text)
    $t = $Text

    # Replace underscores with spaces
    $t = $t -replace '_', ' '

    # Replace dots between letters with spaces (e.g. "Violet.Myers" → "Violet Myers")
    # But preserve dots in numbers like "24.01.02" or "1.5"
    $t = $t -replace '(?<=[a-zA-Z])\.(?=[a-zA-Z])', ' '

    # Remove square brackets and their content if they contain formatting info
    # But keep content if it's meaningful (e.g. "Scene 2")
    # Strategy: remove brackets but keep content
    $t = $t -replace '[\[\]]', ''
    $t = $t -replace '[\{\}]', ''

    # Remove parentheses that are empty or contain only formatting
    $t = $t -replace '\(\s*\)', ''

    # Remove stray apostrophe-s (e.g. "Ava Addams's" → "Ava Addams")
    $t = $t -replace "'s\b", ''

    # Replace multiple hyphens with single " - "
    $t = $t -replace '\s*-{2,}\s*', ' - '
    # Replace hyphens surrounded by spaces with standard separator
    # But DON'T touch hyphens within compound words like "3-Way" or "Step-Dad"
    $t = $t -replace '\s+-\s+', ' - '
    # Fix hyphens at end of words (e.g. "Reincarnated- Jackie" → "Reincarnated - Jackie")
    $t = $t -replace '(?<=\w)-(?=\s)', ' -'
    # Fix hyphens at start of words (e.g. "Jackie -Banana" → "Jackie - Banana")
    $t = $t -replace '(?<=\s)-(?=\w)', '- '

    # Remove stray commas at start/end
    $t = $t -replace '^\s*,\s*', ''
    $t = $t -replace '\s*,\s*$', ''

    # Collapse multiple spaces
    $t = $t -replace '\s{2,}', ' '

    return $t.Trim(' ', '-')
}

# -----------------------------------------------------------------------------
# Apply Title Case with ALL CAPS for known acronyms
# -----------------------------------------------------------------------------
function Invoke-TitleCase {
    param([string]$Text)

    if ([string]::IsNullOrWhiteSpace($Text)) { return $Text }

    # First, convert ALL CAPS text to Title Case (but not acronyms)
    # If the text is mostly uppercase, convert to lower first
    $upperChars = ($Text -replace '[^A-Z]', '').Length
    $lowerChars = ($Text -replace '[^a-z]', '').Length
    if ($upperChars -gt $lowerChars * 2) {
        # Mostly uppercase — convert to lower first
        $Text = $Text.ToLower()
    }

    # Split into words and capitalize
    $words = $Text -split '(\s+)'  # keep whitespace
    $result = @()
    foreach ($w in $words) {
        if ($w -match '^\s+$') {
            $result += $w
            continue
        }
        if ([string]::IsNullOrWhiteSpace($w)) { continue }

        # Check if this word is a known acronym (case-insensitive)
        $isAcronym = $false
        foreach ($a in $acronyms) {
            if ($w -ieq $a) {
                $result += $a.ToUpper()
                $isAcronym = $true
                break
            }
        }
        if ($isAcronym) { continue }

        # Skip words that are entirely non-alpha (numbers, punctuation)
        if ($w -notmatch '[a-zA-Z]') {
            $result += $w
            continue
        }

        # Preserve alphanumeric words like "38G", "4K", "1080p"
        # Don't lowercase the alpha part of mixed alphanumeric words
        if ($w -match '^\d+[a-zA-Z]$' -or $w -match '^\d+[a-zA-Z]+\d*$') {
            $result += $w.ToUpper()
            continue
        }

        # Title Case: capitalize first letter, lowercase rest
        # But preserve internal capitals (e.g. "iPhone")
        if ($w.Length -le 2) {
            # Short word — capitalize first letter
            $result += $w.Substring(0,1).ToUpper() + $w.Substring(1).ToLower()
        } else {
            $result += $w.Substring(0,1).ToUpper() + $w.Substring(1).ToLower()
        }
    }

    $final = ($result -join '').Trim()

    # Fix common capitalization issues
    # "With" should stay capitalized in titles
    # Roman numerals
    $final = $final -replace '\bIII\b', 'III'
    $final = $final -replace '\bII\b', 'II'
    $final = $final -replace '\bIV\b', 'IV'

    return $final
}

# -----------------------------------------------------------------------------
# Detect the lead token (category, subcategory, or studio)
# Returns: @{ Lead='Asian'; Sub='JAV'; Studio=''; Prefix=''; StudioName='' }
# -----------------------------------------------------------------------------
function Find-LeadToken {
    param([string]$Description)

    $descLower = $Description.ToLower()

    # 1. Check TS indicators (highest priority — TS overrides other categories)
    foreach ($kw in $tsKeywords) {
        if ($descLower -match "\b$([regex]::Escape($kw))\b") {
            return @{ Lead = 'TS'; Sub = ''; Studio = ''; Prefix = ''; StudioName = ''; Keyword = $kw }
        }
    }

    # 2. Check prefixed studios (TTL → Teen, Showy Beauty → Teen, Asian Street Meat → Asian)
    foreach ($key in $prefixedStudios.Keys) {
        if ($descLower -match "\b$([regex]::Escape($key))\b") {
            $entry = $prefixedStudios[$key]
            return @{
                Lead      = $entry.Prefix
                Sub       = if ($entry.Prefix -eq 'Asian') { 'JAV' } else { '' }
                Studio    = $entry.Studio
                Prefix    = $entry.Prefix
                StudioName = $entry.Studio
                Keyword   = $key
            }
        }
    }

    # 3. Check Asian keywords (Japanese → Asian - JAV, Chinese → Asian - Chinese)
    foreach ($key in $asianKeywords.Keys) {
        if ($descLower -match "\b$([regex]::Escape($key))\b") {
            $entry = $asianKeywords[$key]
            return @{ Lead = $entry.Lead; Sub = $entry.Sub; Studio = ''; Prefix = ''; StudioName = ''; Keyword = $key }
        }
    }

    # 4. Check nationality keywords (Russian, German, Brazilian, Latina, Ebony)
    #    Note: "Black" is handled separately to avoid false positives with clothing
    foreach ($key in $nationalityKeywords.Keys) {
        if ($descLower -match "\b$([regex]::Escape($key))\b") {
            return @{ Lead = $nationalityKeywords[$key]; Sub = ''; Studio = ''; Prefix = ''; StudioName = ''; Keyword = $key }
        }
    }

    # 4b. Check Black — only if NOT followed by a clothing item
    if ($descLower -match '\bblack\b' -and $descLower -notmatch $blackClothingPattern) {
        return @{ Lead = 'Black'; Sub = ''; Studio = ''; Prefix = ''; StudioName = ''; Keyword = 'black' }
    }

    # 5. Check Euro keywords (French, Italian, Czech → Euro)
    foreach ($kw in $euroKeywords) {
        if ($descLower -match "\b$([regex]::Escape($kw))\b") {
            return @{ Lead = 'Euro'; Sub = ''; Studio = ''; Prefix = ''; StudioName = ''; Keyword = $kw }
        }
    }

    # 6. Check lead studios (BRCC, Hookup Hotshot, etc.)
    foreach ($key in $leadStudios.Keys) {
        if ($descLower -match "\b$([regex]::Escape($key))\b") {
            return @{ Lead = $leadStudios[$key]; Sub = ''; Studio = $leadStudios[$key]; Prefix = ''; StudioName = $leadStudios[$key]; Keyword = $key }
        }
    }

    # 7. Check Teen indicators
    foreach ($kw in $teenKeywords) {
        if ($descLower -match "\b$([regex]::Escape($kw))\b") {
            return @{ Lead = 'Teen'; Sub = ''; Studio = ''; Prefix = ''; StudioName = ''; Keyword = $kw }
        }
    }

    # 8. Check Amateur indicators
    foreach ($kw in $amateurKeywords) {
        if ($descLower -match "\b$([regex]::Escape($kw))\b") {
            return @{ Lead = 'Amateur'; Sub = ''; Studio = ''; Prefix = ''; StudioName = ''; Keyword = $kw }
        }
    }

    # 9. Check Compilation indicators
    foreach ($kw in $compilationKeywords) {
        if ($descLower -match "$([regex]::Escape($kw))") {
            return @{ Lead = 'Compilation'; Sub = ''; Studio = ''; Prefix = ''; StudioName = ''; Keyword = $kw }
        }
    }

    # 10. Default: UI
    return @{ Lead = 'UI'; Sub = ''; Studio = ''; Prefix = ''; StudioName = ''; Keyword = '' }
}

# -----------------------------------------------------------------------------
# Find secondary studio in the description
# Returns: @{ Name = canonical name; Keyword = matched keyword } or $null
# -----------------------------------------------------------------------------
function Find-SecondaryStudio {
    param([string]$Description)

    $descLower = $Description.ToLower()

    # Check secondary studios (longest keys first to avoid partial matches)
    $sortedKeys = $secondaryStudios.Keys | Sort-Object { $_.Length } -Descending
    foreach ($key in $sortedKeys) {
        if ($descLower -match "\b$([regex]::Escape($key))\b") {
            return @{ Name = $secondaryStudios[$key]; Keyword = $key }
        }
    }

    return $null
}

# -----------------------------------------------------------------------------
# Heuristic performer name detection
# Finds two-word capitalized sequences that aren't common non-name words
# Returns: array of detected performer names
# -----------------------------------------------------------------------------
function Find-PerformerNames {
    param([string]$Description)

    if ([string]::IsNullOrWhiteSpace($Description)) { return @() }

    # Split into tokens — split on spaces, hyphens, and dots
    # This handles cases like "Violet.Myers" → ["Violet", "Myers"]
    # and "Yumi Sin-SOLO" → ["Yumi", "Sin", "SOLO"]
    $tokens = $Description -split '[\s\-.]+'

    # Find sequences of consecutive capitalized words that aren't non-name words
    $names = @()
    $currentSeq = @()

    foreach ($word in $tokens) {
        # Clean the word of punctuation for analysis
        $cleanWord = $word -replace '[^a-zA-Z0-9'']', ''
        if ([string]::IsNullOrWhiteSpace($cleanWord)) {
            if ($currentSeq.Count -ge 2) {
                $names += ($currentSeq -join ' ')
            }
            $currentSeq = @()
            continue
        }

        # Check if word starts with uppercase letter
        $startsUpper = $cleanWord -match '^[A-Z]'
        # Check if word is a known non-name word
        $isNonName = $nonNameWords.Contains($cleanWord)
        # Check if word is entirely numeric or too short
        $isNumeric = $cleanWord -match '^\d+$'
        $isTooShort = $cleanWord.Length -lt 2

        # Check if word looks like a name:
        # - Starts with uppercase
        # - Not in non-name list
        # - Not purely numeric
        # - At least 2 characters
        # - Contains at least one letter
        $hasLetter = $cleanWord -match '[a-zA-Z]'

        if ($startsUpper -and -not $isNonName -and -not $isNumeric -and -not $isTooShort -and $hasLetter) {
            $currentSeq += $cleanWord
        } else {
            if ($currentSeq.Count -ge 2) {
                $names += ($currentSeq -join ' ')
            }
            $currentSeq = @()
        }
    }

    # Don't forget the last sequence
    if ($currentSeq.Count -ge 2) {
        $names += ($currentSeq -join ' ')
    }

    # Filter out sequences that are clearly not names:
    # - Only keep 2-word sequences (3+ words are too likely to be titles/descriptions)
    # - Both words must be at least 3 characters
    # - The sequence matches a known studio (shouldn't be treated as performer)
    $filtered = @()
    foreach ($name in $names) {
        $words = $name -split ' '
        if ($words.Count -ne 2) { continue }  # Only 2-word names

        # Both words must be at least 3 characters
        $tooShort = $false
        foreach ($w in $words) {
            if ($w.Length -lt 3) { $tooShort = $true; break }
        }
        if ($tooShort) { continue }

        # Check if this matches a known studio
        # Use word-boundary regex to avoid partial matches (e.g. "asm" matching "jasmin")
        $nameLower = $name.ToLower()
        $isStudio = $false
        foreach ($sKey in $leadStudios.Keys) {
            if ($nameLower -match "\b$([regex]::Escape($sKey))\b") { $isStudio = $true; break }
        }
        if (-not $isStudio) {
            foreach ($sKey in $prefixedStudios.Keys) {
                if ($nameLower -match "\b$([regex]::Escape($sKey))\b") { $isStudio = $true; break }
            }
        }
        if (-not $isStudio) {
            foreach ($sKey in $secondaryStudios.Keys) {
                if ($nameLower -match "\b$([regex]::Escape($sKey))\b") { $isStudio = $true; break }
            }
        }
        if ($isStudio) { continue }

        $filtered += $name
    }

    return $filtered
}

# -----------------------------------------------------------------------------
# Remove detected performer names and category/studio keywords from description
# -----------------------------------------------------------------------------
function Get-CleanDescription {
    param(
        [string]$Description,
        [array]$Performers,
        [string]$LeadKeyword,
        [string]$StudioName,
        [string]$StudioKeyword
    )

    $result = $Description

    # Remove performer names
    foreach ($perf in $Performers) {
        $escaped = [regex]::Escape($perf)
        $result = $result -replace "(?i)\b$escaped\b", ''
    }

    # Remove the lead token keyword (e.g. "Japanese", "Russian", "Brazilian")
    if ($LeadKeyword) {
        $escaped = [regex]::Escape($LeadKeyword)
        $result = $result -replace "(?i)\b$escaped\b", ''
    }

    # Remove studio name and studio keyword
    if ($StudioName) {
        $escaped = [regex]::Escape($StudioName)
        $result = $result -replace "(?i)\b$escaped\b", ''
    }
    if ($StudioKeyword -and $StudioKeyword -ne $StudioName) {
        $escaped = [regex]::Escape($StudioKeyword)
        $result = $result -replace "(?i)\b$escaped\b", ''
    }

    # Clean up: remove leading/trailing hyphens, collapse spaces
    $result = $result -replace '^\s*-\s*', ''
    $result = $result -replace '\s*-\s*$', ''
    $result = $result -replace '^\s*,\s*', ''
    $result = $result -replace '\s*,\s*$', ''
    $result = $result -replace '\s{2,}', ' '
    $result = $result.Trim(' ', '-', ',')

    return $result
}

# -----------------------------------------------------------------------------
# Determine confidence level based on detection quality
# -----------------------------------------------------------------------------
function Get-Confidence {
    param(
        [array]$Performers,
        [string]$LeadToken,
        [string]$Studio
    )

    # HIGH: performer name detected (2+ words)
    if ($Performers.Count -gt 0) {
        $firstPerf = $Performers[0]
        $wordCount = ($firstPerf -split ' ').Count
        if ($wordCount -ge 2) { return "High" }
        return "Medium"
    }

    # MEDIUM: studio detected but no performer
    if ($Studio) { return "Medium" }

    # LOW: category detected but no performer or studio
    if ($LeadToken -ne 'UI') { return "Low" }

    # NONE: only UI
    return "None"
}

# -----------------------------------------------------------------------------
# Build the new filename from all components
# -----------------------------------------------------------------------------
# Ordering rules:
#   1. Performer found:
#      Category - [Sub] - Performer - [Studio] - Description
#      Performer - [Studio] - Description        (no category → no UI)
#   2. No performer, studio found:
#      Category - [Sub] - Studio - UI - Description
#      Studio - UI - Description                  (no category)
#   3. No performer, no studio, category found:
#      Category - [Sub] - UI - Description
#   4. Nothing found:
#      UI - Description
function Build-NewFilename {
    param(
        [string]$LeadToken,       # Euro, Teen, Asian, Russian, etc. or UI
        [string]$Subcategory,     # JAV, Chinese, Thai, or ""
        [array]$Performers,       # detected performer names
        [string]$Studio,          # secondary studio name or ""
        [string]$Description,     # cleaned description
        [string]$Resolution,      # "1080" or ""
        [string]$Extension        # ".mp4"
    )

    $parts = @()
    $hasCategory = ($LeadToken -ne 'UI')
    $hasPerformer = ($Performers.Count -gt 0)
    $hasStudio = (-not [string]::IsNullOrWhiteSpace($Studio))

    # 1. Category lead token (if any)
    if ($hasCategory) {
        $parts += $LeadToken
    }

    # 2. Subcategory (only after Asian)
    if ($Subcategory) {
        $parts += $Subcategory
    }

    # 3. Performer(s) — if found, no UI is ever inserted
    if ($hasPerformer) {
        $parts += ($Performers -join ' - ')
        # Studio goes after performer
        if ($hasStudio) {
            $parts += $Studio
        }
    }
    # 4. No performer — studio goes next, then UI
    elseif ($hasStudio) {
        $parts += $Studio
        $parts += 'UI'
    }
    # 5. No performer, no studio — UI goes next (if category exists)
    elseif ($hasCategory) {
        $parts += 'UI'
    }
    # 6. Nothing at all — UI is the lead
    else {
        $parts += 'UI'
    }

    # Description
    if (-not [string]::IsNullOrWhiteSpace($Description)) {
        $parts += $Description
    }

    # Join with separator
    $name = $parts -join ' - '

    # Append resolution
    if (-not [string]::IsNullOrWhiteSpace($Resolution)) {
        $name += " ($Resolution)"
    }

    # Sanitise forbidden characters: / \ : * ? " < > |
    $name = $name -replace '[\\/:\*\?"<>\|]', ''

    # Collapse double spaces
    $name = $name -replace '\s{2,}', ' '
    $name = $name.Trim(' ', '-')

    return $name + $Extension
}

# =============================================================================
# Main Processing
# =============================================================================

Write-Step "Scanning Unfiled directory: $UnfiledDir"

if (-not (Test-Path $UnfiledDir)) {
    Write-Err "Unfiled directory not found: $UnfiledDir"
    exit 1
}

$allFiles = Get-ChildItem -LiteralPath $UnfiledDir -File
if ($SourceFilter) {
    $files = $allFiles | Where-Object { $_.Name -like "*$SourceFilter*" }
} else {
    $files = $allFiles
}

# Apply sample size limit if specified
if ($SampleSize -gt 0 -and $files.Count -gt $SampleSize) {
    $files = $files | Select-Object -First $SampleSize
    Write-Ok "$($files.Count) files to process (sampled from $($allFiles.Count), filter: '$SourceFilter')"
} else {
    Write-Ok "$($files.Count) files to process (filter: '$SourceFilter')"
}

if ($files.Count -eq 0) {
    Write-Warn "No files matched the filter. Exiting."
    exit 0
}

# Confidence order for filtering
$confidenceOrder = @{ "High" = 3; "Medium" = 2; "Low" = 1; "None" = 0 }
$minConfidenceVal = $confidenceOrder[$MinConfidence]

$results = [System.Collections.Generic.List[pscustomobject]]::new()
$stats = @{ High = 0; Medium = 0; Low = 0; None = 0 }
$leadStats = @{}
$counter = 0
$startTime = Get-Date

foreach ($f in $files) {
    $counter++
    if ($counter % 200 -eq 0) {
        $elapsed = (Get-Date) - $startTime
        $rate = [math]::Round($counter / $elapsed.TotalSeconds, 1)
        Write-Step "Processing $counter / $($files.Count) ($rate files/sec) ..."
    }

    $parsed = Parse-EpornerFilename -Filename $f.Name

    # --- Phase 1: Clean text ---
    # Normalise obfuscation
    $normDesc = Invoke-TextNormalisation -Text $parsed.Description
    $normalised = ($normDesc -ne $parsed.Description)

    # Remove junk text
    $cleanDesc = Remove-JunkText -Text $normDesc

    # Remove formatting artifacts (brackets, underscores, etc.)
    $cleanDesc = Remove-FormattingArtifacts -Text $cleanDesc

    # --- Phase 2: Detect lead token ---
    $leadInfo = Find-LeadToken -Description $cleanDesc
    $leadToken = $leadInfo.Lead
    $subcategory = $leadInfo.Sub
    $leadKeyword = $leadInfo.Keyword
    $prefixStudio = $leadInfo.StudioName  # studio from prefixed studios (TTL, Showy Beauty)

    # --- Phase 3: Find secondary studio ---
    $secondaryStudioInfo = Find-SecondaryStudio -Description $cleanDesc
    $secondaryStudio = ""
    $secondaryStudioKeyword = ""
    if ($secondaryStudioInfo) {
        $secondaryStudio = $secondaryStudioInfo.Name
        $secondaryStudioKeyword = $secondaryStudioInfo.Keyword
    }

    # Determine which studio to use in the output
    $outputStudio = $prefixStudio
    $outputStudioKeyword = $leadInfo.Keyword  # keyword from prefixed studio detection
    if (-not $outputStudio) {
        $outputStudio = $secondaryStudio
        $outputStudioKeyword = $secondaryStudioKeyword
    }

    # --- Phase 3b: Pre-clean description for performer detection ---
    # Remove studio names and lead token keywords from the description BEFORE
    # running performer detection, so they don't contaminate name sequences.
    $descForPerfDetection = $cleanDesc

    # Remove studio keyword and canonical name
    if ($outputStudioKeyword) {
        $escaped = [regex]::Escape($outputStudioKeyword)
        $descForPerfDetection = $descForPerfDetection -replace "(?i)\b$escaped\b", ''
    }
    if ($outputStudio -and $outputStudio -ne $outputStudioKeyword) {
        $escaped = [regex]::Escape($outputStudio)
        $descForPerfDetection = $descForPerfDetection -replace "(?i)\b$escaped\b", ''
    }

    # Remove lead token keyword (e.g. "japanese", "russian", "brazilian")
    if ($leadKeyword) {
        $escaped = [regex]::Escape($leadKeyword)
        $descForPerfDetection = $descForPerfDetection -replace "(?i)\b$escaped\b", ''
    }

    # Remove ALL synonyms for the same lead token (e.g. both "black" and "ebony")
    if ($leadToken -eq 'Black') {
        $descForPerfDetection = $descForPerfDetection -replace '(?i)\bblack\b', ''
        $descForPerfDetection = $descForPerfDetection -replace '(?i)\bebony\b', ''
    }
    if ($leadToken -eq 'Brazilian') {
        $descForPerfDetection = $descForPerfDetection -replace '(?i)\bbrazilian\b', ''
        $descForPerfDetection = $descForPerfDetection -replace '(?i)\bbrasil\b', ''
        $descForPerfDetection = $descForPerfDetection -replace '(?i)\bbrasilian\b', ''
    }
    if ($leadToken -eq 'Latina') {
        $descForPerfDetection = $descForPerfDetection -replace '(?i)\blatina\b', ''
        $descForPerfDetection = $descForPerfDetection -replace '(?i)\blatin\b', ''
        $descForPerfDetection = $descForPerfDetection -replace '(?i)\bcolombian\b', ''
        $descForPerfDetection = $descForPerfDetection -replace '(?i)\bmexican\b', ''
        $descForPerfDetection = $descForPerfDetection -replace '(?i)\bcuban\b', ''
    }

    # Also remove TS keywords from description for performer detection
    if ($leadToken -eq 'TS') {
        foreach ($kw in $tsKeywords) {
            $escaped = [regex]::Escape($kw)
            $descForPerfDetection = $descForPerfDetection -replace "(?i)\b$escaped\b", ''
        }
    }

    # Clean up spacing after removals
    $descForPerfDetection = $descForPerfDetection -replace '^\s*-\s*', ''
    $descForPerfDetection = $descForPerfDetection -replace '\s*-\s*$', ''
    $descForPerfDetection = $descForPerfDetection -replace '\s{2,}', ' '
    $descForPerfDetection = $descForPerfDetection.Trim(' ', '-', ',')

    # --- Phase 4: Detect performer names (heuristic) ---
    $performers = Find-PerformerNames -Description $descForPerfDetection

    # Filter out performers that match the studio name (avoid duplication)
    if ($performers.Count -gt 0 -and $outputStudio) {
        $performers = @($performers | Where-Object {
            $_ -notmatch [regex]::Escape($outputStudio)
        })
    }

    # --- Phase 4b: Apply reviewer corrections (from v1 review) ---
    # These override the heuristic detection with known-correct values
    $correctionApplied = $false
    if ($performerCorrections.ContainsKey($parsed.EpornerID)) {
        $correctedPerformers = $performerCorrections[$parsed.EpornerID]
        if ($correctedPerformers.Count -gt 0) {
            $performers = $correctedPerformers
            $correctionApplied = $true
        }
    }

    # Apply lead token corrections
    if ($leadTokenCorrections.ContainsKey($parsed.EpornerID)) {
        $ltCorr = $leadTokenCorrections[$parsed.EpornerID]
        $leadToken = $ltCorr.Lead
        if ($ltCorr.Sub) {
            $subcategory = $ltCorr.Sub
        }
        # Update leadKeyword for description cleanup
        if ($ltCorr.Lead -eq 'Asian' -and $subcategory -eq 'JAV') {
            $leadKeyword = 'japanese'
        }
        $correctionApplied = $true
    }

    # Apply studio corrections
    if ($studioCorrections.ContainsKey($parsed.EpornerID)) {
        $correctedStudio = $studioCorrections[$parsed.EpornerID]
        # Don't set studio if it's the same as the lead token (avoids duplication)
        if ($leadToken -ne $correctedStudio) {
            $outputStudio = $correctedStudio
            $outputStudioKeyword = $outputStudio
        } else {
            # Lead token is the studio, so don't add studio again
            $outputStudio = ""
            $outputStudioKeyword = ""
        }
        $correctionApplied = $true
    }

    # --- Phase 5: Clean description (final pass) ---
    # Re-clean the description with the corrected performers/studio/lead token
    # Remove corrected performer names from description too
    $finalDesc = Get-CleanDescription `
        -Description $cleanDesc `
        -Performers $performers `
        -LeadKeyword $leadKeyword `
        -StudioName $outputStudio `
        -StudioKeyword $outputStudioKeyword

    # Also remove corrected performer names that weren't in the original detection
    if ($correctionApplied -and $performerCorrections.ContainsKey($parsed.EpornerID)) {
        foreach ($perf in $performerCorrections[$parsed.EpornerID]) {
            $escaped = [regex]::Escape($perf)
            $finalDesc = $finalDesc -replace "(?i)\b$escaped\b", ''
        }
        # Also remove common obfuscated/variant forms
        $finalDesc = $finalDesc -replace '(?i)\bAmberA\b', ''
        $finalDesc = $finalDesc -replace '(?i)\bCourtney_Luv\b', ''
        $finalDesc = $finalDesc -replace '(?i)\bChloeCherry\b', ''
        $finalDesc = $finalDesc -replace '(?i)\bViolet\.myers\b', ''
        $finalDesc = $finalDesc -replace '(?i)\bViolet\.Myers\b', ''
        $finalDesc = $finalDesc -replace '(?i)\bDand@ra\b', ''
        $finalDesc = $finalDesc -replace '(?i)\bMor@es\b', ''
        $finalDesc = $finalDesc -replace '(?i)\bM1LF\b', ''
    }

    # Remove synonyms from final description too
    if ($leadToken -eq 'Black') {
        $finalDesc = $finalDesc -replace '(?i)\bblack\b', ''
        $finalDesc = $finalDesc -replace '(?i)\bebony\b', ''
    }
    if ($leadToken -eq 'Brazilian') {
        $finalDesc = $finalDesc -replace '(?i)\bbrazilian\b', ''
        $finalDesc = $finalDesc -replace '(?i)\bbrasil\b', ''
    }
    if ($leadToken -eq 'Latina') {
        $finalDesc = $finalDesc -replace '(?i)\blatina\b', ''
        $finalDesc = $finalDesc -replace '(?i)\blatin\b', ''
        $finalDesc = $finalDesc -replace '(?i)\bcolombian\b', ''
    }
    if ($leadToken -eq 'TS') {
        foreach ($kw in $tsKeywords) {
            $escaped = [regex]::Escape($kw)
            $finalDesc = $finalDesc -replace "(?i)\b$escaped\b", ''
        }
    }

    # Clean up after synonym removal
    $finalDesc = $finalDesc -replace '^\s*-\s*', ''
    $finalDesc = $finalDesc -replace '\s*-\s*$', ''
    $finalDesc = $finalDesc -replace '\s{2,}', ' '
    $finalDesc = $finalDesc.Trim(' ', '-', ',')

    # Apply Title Case to the description
    $finalDesc = Invoke-TitleCase -Text $finalDesc

    # Apply Title Case to performer names
    $formattedPerformers = @()
    foreach ($p in $performers) {
        $formattedPerformers += (Invoke-TitleCase -Text $p)
    }

    # --- Phase 5b: Append eporner ID to description for duplicate detection ---
    # The eporner ID is added as a bracketed suffix to the description, e.g.
    # "Big Tit MILF Gets Anal Facial [RPaWJ5SNhuA]"
    if ($parsed.EpornerID -and $finalDesc) {
        $finalDesc = "$finalDesc [$($parsed.EpornerID)]"
    } elseif ($parsed.EpornerID -and -not $finalDesc) {
        # If description is empty, just use the ID
        $finalDesc = "[$($parsed.EpornerID)]"
    }

    # --- Phase 6: Build new filename ---
    $newName = Build-NewFilename `
        -LeadToken $leadToken `
        -Subcategory $subcategory `
        -Performers $formattedPerformers `
        -Studio $outputStudio `
        -Description $finalDesc `
        -Resolution $parsed.Resolution `
        -Extension $parsed.Extension

    # --- Build notes ---
    $notes = @()
    if ($correctionApplied) { $notes += "reviewer-corrected" }
    if ($normalised) { $notes += "obfuscation-normalised" }
    if ($performers.Count -gt 1) { $notes += "multi-performer" }
    if ($performers.Count -eq 0 -and $leadToken -ne 'UI') { $notes += "no-performer-found" }
    if ($outputStudio) { $notes += "studio:$outputStudio" }
    if ($subcategory) { $notes += "sub:$subcategory" }
    if ($newName -eq $f.Name) { $notes += "no-change" }
    $notesStr = ($notes -join "; ")

    # --- Confidence ---
    $confidence = Get-Confidence -Performers $formattedPerformers -LeadToken $leadToken -Studio $outputStudio
    $stats[$confidence]++
    if ($leadStats.ContainsKey($leadToken)) {
        $leadStats[$leadToken]++
    } else {
        $leadStats[$leadToken] = 1
    }

    # --- Leading token for CSV ---
    $leadingTokenStr = $leadToken
    if ($subcategory) { $leadingTokenStr += " - $subcategory" }
    if ($formattedPerformers.Count -gt 0) {
        $leadingTokenStr += " - " + ($formattedPerformers -join "; ")
    }

    $results.Add([pscustomobject]@{
        OldFilename       = $f.Name
        NewFilename       = $newName
        EpornerID         = $parsed.EpornerID
        LeadingToken      = $leadToken
        Subcategory       = $subcategory
        MatchedPerformers = ($formattedPerformers -join "; ")
        MatchedStudio     = $outputStudio
        Confidence        = $confidence
        Resolution        = $parsed.Resolution
        Description       = $finalDesc
        Notes             = $notesStr
    })
}

# =============================================================================
# Report
# =============================================================================

$elapsed = (Get-Date) - $startTime
Write-Ok "Processed $($results.Count) files in $([math]::Round($elapsed.TotalSeconds, 1))s"

# Filter by confidence
$filtered = $results | Where-Object { $confidenceOrder[$_.Confidence] -ge $minConfidenceVal }

Write-Host ""
Write-Host "=== Match Summary ===" -ForegroundColor Green
Write-Host "  Total files processed: $($results.Count)"
Write-Host "  High confidence:   $($stats.High)" -ForegroundColor Green
Write-Host "  Medium confidence: $($stats.Medium)" -ForegroundColor Yellow
Write-Host "  Low confidence:    $($stats.Low)" -ForegroundColor DarkYellow
Write-Host "  No match:          $($stats.None)" -ForegroundColor DarkGray

Write-Host ""
Write-Host "  Lead token breakdown:" -ForegroundColor Cyan
foreach ($lt in ($leadStats.Keys | Sort-Object)) {
    Write-Host "    $lt : $($leadStats[$lt])" -ForegroundColor White
}

Write-Host ""
Write-Host "  Showing >= $MinConfidence : $($filtered.Count) files" -ForegroundColor Cyan

# Write CSV report
$reportDir = Split-Path $OutputPath -Parent
if (-not (Test-Path $reportDir)) { New-Item -ItemType Directory -Path $reportDir -Force | Out-Null }
$filtered | Export-Csv -Path $OutputPath -NoTypeInformation -Encoding UTF8
Write-Ok "CSV report written to $OutputPath"

# Show sample of proposed renames
Write-Host ""
Write-Host "=== Sample Proposed Renames (first 25) ===" -ForegroundColor Green
$sample = $filtered | Select-Object -First 25
foreach ($r in $sample) {
    $colour = switch ($r.Confidence) {
        "High"   { "Green" }
        "Medium" { "Yellow" }
        "Low"    { "DarkYellow" }
        "None"   { "DarkGray" }
    }
    $oldShort = $r.OldFilename -replace 'EPORNER\.COM\s*-\s*', ''
    if ($oldShort.Length -gt 60) { $oldShort = $oldShort.Substring(0, 57) + "..." }
    $newShort = $r.NewFilename
    if ($newShort.Length -gt 60) { $newShort = $newShort.Substring(0, 57) + "..." }

    Write-Host "  [$($r.Confidence)] " -ForegroundColor $colour -NoNewline
    Write-Host $oldShort
    Write-Host "       -> " -NoNewline
    Write-Host $newShort -ForegroundColor White
    if ($r.MatchedPerformers) { Write-Host "       Performers: $($r.MatchedPerformers)" -ForegroundColor DarkGray }
    if ($r.MatchedStudio)     { Write-Host "       Studio: $($r.MatchedStudio)" -ForegroundColor DarkGray }
    if ($r.Subcategory)       { Write-Host "       Sub: $($r.Subcategory)" -ForegroundColor DarkGray }
    if ($r.Notes)             { Write-Host "       Notes: $($r.Notes)" -ForegroundColor DarkGray }
    Write-Host ""
}

# =============================================================================
# Execute renames (only if -Execute is passed)
# =============================================================================

if ($Execute) {
    Write-Host ""
    Write-Host "=== EXECUTING RENAMES ===" -ForegroundColor Red
    Write-Host "  Files to rename: $($filtered.Count)" -ForegroundColor Red
    Write-Host "  Source: $UnfiledDir" -ForegroundColor Red
    Write-Host "  Target: $VideoDir" -ForegroundColor Red
    Write-Host ""
    Write-Host "  Type 'yes' to confirm: " -NoNewline -ForegroundColor Red
    $confirmation = Read-Host

    if ($confirmation -ne "yes") {
        Write-Warn "Rename cancelled by user."
        exit 0
    }

    $renamed = 0
    $skipped = 0
    $errors  = 0

    foreach ($r in $filtered) {
        $sourcePath = Join-Path $UnfiledDir $r.OldFilename
        $destPath   = Join-Path $VideoDir $r.NewFilename

        if (-not (Test-Path -LiteralPath $sourcePath)) {
            Write-Warn "Source not found: $($r.OldFilename)"
            $skipped++
            continue
        }

        if (Test-Path -LiteralPath $destPath) {
            Write-Warn "Target exists, skipping: $($r.NewFilename)"
            $skipped++
            continue
        }

        try {
            Move-Item -LiteralPath $sourcePath -Destination $destPath
            $renamed++
        } catch {
            Write-Err "Failed: $($r.OldFilename) -> $($r.NewFilename): $($_.Exception.Message)"
            $errors++
        }
    }

    Write-Host ""
    Write-Host "=== Rename Complete ===" -ForegroundColor Green
    Write-Host "  Renamed: $renamed"
    Write-Host "  Skipped: $skipped"
    Write-Host "  Errors:  $errors"
} else {
    Write-Host ""
    Write-Host "DRY RUN - no files were renamed." -ForegroundColor Yellow
    Write-Host "To execute, run with -Execute (and optionally -MinConfidence High)" -ForegroundColor Yellow
}

# =============================================================================
# Generate Excel spreadsheet for review (unless -NoExcel)
# =============================================================================

if (-not $NoExcel -and $filtered.Count -gt 0) {
    $excelPath = [System.IO.Path]::ChangeExtension($OutputPath, ".xlsx")
    $excelScript = Join-Path $PSScriptRoot "New-RenameExcelReport.ps1"

    if (Test-Path $excelScript) {
        Write-Step "Generating Excel spreadsheet ..."
        try {
            & $excelScript -CsvPath $OutputPath -OutputPath $excelPath
            if (Test-Path $excelPath) {
                Write-Ok "Excel spreadsheet written to $excelPath"
            } else {
                Write-Warn "Excel generation did not produce a file"
            }
        } catch {
            Write-Warn "Excel generation failed: $($_.Exception.Message)"
            Write-Warn "CSV report is still available at $OutputPath"
        }
    } else {
        Write-Warn "Excel helper script not found: $excelScript"
        Write-Warn "CSV report is still available at $OutputPath"
    }
}
