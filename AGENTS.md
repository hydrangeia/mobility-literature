# Project instructions

- Keep the main goal on carrier-mobility paper discovery and coverage across COF, MOF, organic small-molecule/molecular semiconductor, hybrid perovskite, and inorganic 2D materials.
- Keep candidate, likely mobility, confirmed numerical mobility, and verified evidence as separate states. Never infer a mobility value from conductivity, diffusion, or an abstract-only hint.
- Exclude ionic/proton mobility and diffusion from electronic carrier-mobility evidence; mixed-topic papers remain eligible when they explicitly report electron/hole mobility.
- Treat source PDFs and earlier agent outputs as read-only. Import into new files and preserve raw source references.
- Do not crawl entire disks or servers. Search only folders the user names for a specific task.
- Read credentials from environment variables. Never hard-code, print, log, or cache API keys.
- Use caches, bounded retries, resumable cursors/checkpoints, and provenance for every discovery result.
- Keep the implementation small. Do not build a general literature-management system or UI in v1.
