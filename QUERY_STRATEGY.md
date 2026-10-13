# Mobility literature discovery: v1 query strategy

## Purpose and scope

Find papers that report or calculate **electronic carrier mobility** for materials in five target families: covalent organic frameworks (COFs), metal-organic frameworks (MOFs), organic small-molecule or molecular semiconductors, hybrid perovskites, and inorganic two-dimensional (2D) materials. Include experimental and theoretical work. Search results are discovery candidates; a query hit alone never establishes that a paper contains a numerical mobility value.

This is an implementation guide for a practical discovery pipeline, not a registered systematic-review protocol. Retain the query-family identifier and query text with each result so searches can be repeated and coverage gaps can be inspected.

## Query construction

Build queries from three reusable term groups:

1. **Material family** — one family-specific query set below.
2. **Mobility core** — `mobility`, `carrier mobility`, `charge-carrier mobility`, `electron mobility`, `hole mobility`, or `ambipolar mobility`.
3. **Method expansion** — method terms below, paired with the material family. Use these as additional recall queries because some abstracts omit the word “mobility” even when the paper calculates it.

For every family, run direct mobility-core searches first, then method-expansion searches. Keep each request short enough for the provider's query syntax and length limits; split synonym groups into variants instead of relying on a very long Boolean expression. Query syntax varies by source, so the implementation should translate term groups to the provider's supported search fields rather than assume a shared Boolean grammar. Search title and abstract where available, and retain the source, query-family ID, and retrieval date.

### Mobility core and wording variants

- General: `mobility`, `carrier mobility`, `charge-carrier mobility`, `charge transport mobility`
- Carrier-specific: `electron mobility`, `hole mobility`, `ambipolar mobility`, `n-type mobility`, `p-type mobility`
- Common phrasing: `field-effect mobility`, `effective mobility`, `intrinsic mobility`, `band mobility`, `hopping mobility`

Use “mobility” as a discovery cue, not as sufficient evidence. A paper may use the word for ions, molecules, or unrelated topics.

### Method and measurement expansions

Pair each term with a target material-family query; do not run these as material-free searches.

- **Device and experiment:** field-effect transistor, FET, OFET, organic field-effect transistor, transistor mobility, Hall effect, Hall mobility, time-of-flight, TOF, space-charge-limited current, SCLC, transient microwave conductivity, TRMC, time-resolved microwave conductivity, terahertz conductivity, THz, transient photoconductivity, photo-Hall, photoconductivity, contactless mobility.
- **Theory and computation:** deformation-potential theory, Bardeen–Shockley, Boltzmann transport, BTE, electron–phonon coupling, electron–phonon scattering, first-principles transport, ab initio mobility, Fröhlich polaron, polaron transport, Marcus hopping, kinetic Monte Carlo, KMC, hopping transport.
- **Related but not equivalent signals:** diffusion coefficient, diffusion length, mobility–lifetime product, and conductivity can help discover papers, especially in optical measurements. They do not by themselves qualify as a reported mobility result. Flag these for abstract/full-text review.

## Material-family query terms

Use the family name together with mobility-core variants. Keep adjacent or broad terms in separately identifiable query variants so their extra noise is measurable.

| Family | Primary terms | Optional recall variants |
| --- | --- | --- |
| COF | `covalent organic framework`, `covalent organic frameworks`, `COF`, `2D COF` | `conjugated covalent organic framework`, `conductive COF`, named framework/material terms discovered from seed papers |
| MOF | `metal-organic framework`, `metal organic framework`, `MOF`, `2D MOF` | `conductive MOF`, `electrically conductive metal-organic framework`, `porous coordination polymer` (keep this broad variant separately labeled) |
| Organic small-molecule / molecular semiconductor | `organic semiconductor`, `organic molecular semiconductor`, `small-molecule semiconductor`, `molecular crystal`, `organic single crystal`, `molecular semiconductor` | `organic field-effect transistor`, `OFET`, and known material names (for example pentacene, rubrene, or TIPS-pentacene) as separate seed-expansion searches |
| Hybrid perovskite | `hybrid perovskite`, `hybrid organic-inorganic perovskite`, `organic-inorganic halide perovskite`, `organic-inorganic hybrid perovskite`, `metal halide perovskite` | `lead halide perovskite`, `methylammonium perovskite`, `formamidinium perovskite`, `mixed-cation perovskite`; review composition to separate hybrid from all-inorganic compounds |
| Inorganic 2D | `two-dimensional semiconductor`, `2D semiconductor`, `inorganic 2D material`, `monolayer semiconductor`, `few-layer semiconductor`, `transition-metal dichalcogenide`, `TMD`, `TMDC` | `black phosphorus`, `phosphorene`, `MoS2`, `WS2`, `WSe2`, `MXene`, and other inorganic 2D material names as separate seed-expansion searches; retain only electronic carrier mobility results |

Do not require the material name and a named measurement method in the same query: some relevant abstracts state only “mobility.” Conversely, method-only hits must still be associated with at least one target-family term or a known material seed.

## High-precision exclusion and triage policy

### Do not use broad global `NOT` clauses

Avoid excluding `conductivity`, `ion`, `diffusion`, `perovskite`, `framework`, or `mobility` at query time. These terms also occur in eligible papers: conductivity can be the measurement route, hybrid perovskites can show both electronic and ionic transport, and a paper may discuss diffusion alongside carrier mobility. Collect a useful recall set, then apply exclusions to title/abstract evidence while preserving the reason and the original record.

### Exclude or down-rank only on specific evidence

- **Ionic or proton transport only:** exclude from the electronic-mobility dataset when the paper reports only cation, anion, Li/Na/K-ion, proton, hydroxide, or other ionic mobility/conductivity/diffusion, with no indication of electron or hole transport. Examples include solid electrolytes, proton conductors, ion conductors, and ion migration in perovskites. Keep mixed electronic/ionic studies as candidates when electronic mobility is mentioned.
- **Ion mobility in unrelated contexts:** exclude gas-phase ion mobility spectrometry, mass-spectrometry ion mobility, electrophoretic mobility, and biological/medical mobility uses when they do not concern electronic carriers in a target material.
- **Diffusion without mobility:** do not treat self-diffusion, tracer diffusion, ion diffusion, exciton diffusion, diffusion length, or a diffusion coefficient alone as carrier mobility. Keep as a low-confidence candidate if the same record also signals electron/hole transport or a mobility-conversion analysis.
- **Conductivity without mobility:** conductivity, resistivity, carrier concentration, or a mobility–lifetime product alone is not a numerical mobility result. These may remain discovery candidates if the abstract signals a mobility extraction, but must not be marked confirmed.
- **Out-of-scope material or carrier:** exclude records whose relevant mobility concerns molecules in solution, polymer/electrolyte ions, biological transport, or a material outside the five target families, unless another part of the work reports in-scope electronic mobility.

An explicit `electron`, `hole`, `electronic`, `charge-carrier`, `FET mobility`, or equivalent signal takes precedence over a generic ionic-transport cue: mixed-topic papers must not be discarded automatically. Store exclusion decisions as reviewable labels with a short evidence note, rather than deleting records.

## Candidate status signals

Use query hits and abstract cues to prioritize review, while keeping the evidence levels separate:

- **Candidate:** retrieved by a recorded family query or citation expansion; no mobility claim has yet been checked.
- **Likely contains mobility:** title/abstract explicitly signals electron/hole/carrier mobility, or a target material plus a mobility-calculating method. This is a triage label, not a verified result.
- **Confirmed numerical mobility:** a source reports a numerical electronic mobility with a unit and carrier type or an unambiguous carrier context. Record the experimental/computational method and conditions when available.
- **Verified evidence:** the numerical value has a traceable location in the paper or supplement (page/table/figure/equation or SI location) and its context has been checked. Never infer a value from conductivity or diffusion alone.

## Expansion and coverage checks

Use DOI/title matches to deduplicate results across queries and providers. For high-priority seed papers, add references and citing works as separate citation-expansion sources, then classify those records with the same scope and evidence rules. Periodically summarize retrieval and triage counts by family and query family; use low counts to trigger new material-name or method variants. A high hit count is not proof of coverage, and a citation-expanded record remains a candidate until its mobility evidence is checked.
