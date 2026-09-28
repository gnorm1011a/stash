# Group/Movie Metadata Audit

Scope: 3,767 grouped scenes; pipeline created ~1,814 groups, joined ~3,150 scenes, additively propagated movie fields (date/director/studio/urls/title-if-empty) to 3,206 scenes. Propagation only filled EMPTY scene fields - nothing was overwritten.

## Confidence of scene->group->movie chain

| Tier | Memberships | Meaning |
|---|---|---|
| STRONG (direct TPDB name match) | 1,202 | Movie record confidently identified |
| strong resolved (score>=8, date+studio corroborated) | 288 | |
| probable (score 4-7) | 54 | Mostly right, minor uncertainty |
| **WEAK (score<4, name-only)** | **726 across 425 groups** | Movie exists with this name but picked edition/date/studio is a guess |
| no-match / no movie data | 1,524 | Group exists name-only; nothing applied beyond name |

## Hard errors found

| Scene | File | Problem |
|---|---|---|
| 10579 | Britney Foster - American_Ass_1_Scene_2.mp4 | Filename Scene 2 but scene_index=1 and title "American Ass 1 - Scene 1" |
| 14392 | Anal Creampie POV 2 - Scene 2-... | scene_index 2 conflicts with filename-parsed idx 1 |
| 21673 | ...2 On 1 18, Scene 6 (2005)... | Filename year 2005 vs applied date 2004-01-01; group name "2 On 1 18," carries trailing comma |

7 group names have trailing-punctuation junk leaking into scene titles:
`Annette Schwarz Is Slutwoman 2,` `Bone Second Coming,` `Ass Fucked MILFs 6,` `Casting Girls,` `2 On 1 18,` `My Buddy's Hot Mom 4,` `Stacked Slut Supreme 2,`

## 42 late-era picks - almost certainly wrong editions (2000s content resolved to 2016-2022 records)

- `Anal Appeal` -> 2016-04-21 Guilty Desire
- `Anal Club 2` -> 2016-07-18 Exquisite
- `Anal Discipline at School` -> 2018-08-23 Raw Delight
- `Anal Mother Fuckers 4` -> 2017-11-14 Devil's Film
- `Asians Love You Long Time 2` -> 2018-11-20 Devil's Film
- `Ass Fuck 1` -> 2022-03-08 American Hardcore
- `Backdoor Playtime` -> 2017-07-14 Provocative Productions
- `Bangin Milfs` -> 2021-07-26 Blue Bird Films
- `Big Booty Ballers 2` -> 2017-02-06 Black Market XXX
- `Big Racks And Ass Attacks` -> 2017-12-05 Explicit Empire
- `Big Tittie IR MILFS` -> 2016-11-29 Black Magic Pictures
- `Blonde Grannies Love Interracial Anal` -> 2018-10-09 Raven Productions
- `Busty Anal Babes` -> 2016-09-08 Devious Productions
- `Class Reunion 3` -> 2017-03-09 Notorious Productions
- `Cum To Mommy` -> 2016-09-07 Reality Kings
- `Daddy Loves My Big Tits` -> 2016-07-06 Smash Pictures
- `Deep Inside My Tushy` -> 2017-06-30 Provocative Productions
- `Double Teamed White Sluts` -> 2018-11-20 Raven Productions
- `End Game` -> 2018-12-19 Vouyer Media
- `Fucking With The Stars 4` -> 2016-08-01 Naughty Sinners
- `Gang Stars` -> 2018-04-09 Explicit Empire
- `Horny Babysitter Gang Bang` -> 2019-04-26 Cherry Boxxx
- `Horny Maids` -> 2017-05-26 Club Innocence
- `Interracial POV 2` -> 2018-01-08 Snatch Films
- `Long Legs And Beautiful 5` -> 2016-02-19 Immoral Productions
- `Love Your Tits 2` -> 2017-01-31 DDF Network
- `Massive Mammaries 2` -> 2017-08-15 Devil's Films
- `Massive Mammaries 4` -> 2019-06-04 Devil's Films
- `Mature Nymphos Fucked Hard` -> 2017-02-02 Mature NL
- `Mommy Banged A Black Man 3` -> 2017-06-22 Combat Zone
- `My 3Way Fantasy 2` -> 2019-03-29 Cherry Boxxx
- `My Busty Slut` -> 2016-05-24 Allure Films
- `Pretty Wild` -> 2016-03-28 Desire Films
- `Ready To Take It All Right Out The Training Bra 2` -> 2018-04-20 Cherry Boxxx
- `Sinful Juggs` -> 2016-06-09 Explicit Empire
- `Taking Notes While Fucking My Boss` -> 2019-05-16 Raw Delight
- `Teens Try Anal 2` -> 2024-08-06 Simon Wolf
- `Teens Want It All 2` -> 2017-09-28 Explicit Empire
- `Titty Fuck 2` -> 2016-09-20 DDF Network
- `White Boys In The Hood` -> 2017-05-19 Cherry Boxxx
- `You Me and A Friend Makes Three` -> 2016-01-09 Explicit Empire
- `Your Wifes Hot Want to Swing 2` -> 2018-08-31 Baby Doll Pictures

## Remediation applied

| Action | Count |
|---|---|
| Groups cleared of movie fields (weak + late-era tiers) | 438 |
| Scenes stripped of propagated date/studio/director/urls | 742 |
| Scene/group `details` notes with unverified candidate | all of the above |
| Scene 10579 scene_index/title corrected to Scene 2 | done |
| Scene 21673 wrong date (2004) cleared, group renamed | done |
| Comma-suffixed group names fixed (+ member titles) | 7 |

Group-level movie data stripped was recorded as: `[group-audit] Unverified movie match (stripped): "<title>" (<date>, <studio>) <url>` in the group synopsis and member scene details - so the candidate remains visible for review without being asserted as fact.
