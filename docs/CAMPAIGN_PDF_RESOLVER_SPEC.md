# Campaign PDF Resolver Spec

## Contract

`modules.campaign_pdf.campaign_pdf_candidate(registry_entry)` builds the single
candidate path for a campaign PDF from the registry entry's recorded
`source_pdf_path`. `modules.campaign_pdf.resolve_campaign_pdf(registry_entry)`
calls that helper and returns the candidate only when it exists as a file.

Only the recorded filename is canonical. The recorded directory is
machine-specific and must be ignored:

```text
PureWindowsPath(registry_entry["source_pdf_path"]).name
```

Registry entries currently record Windows-native paths, while CI and future
machines may be POSIX. `PureWindowsPath.name` treats both `\` and `/` as
separators, so it extracts the same canonical filename from Windows-recorded and
POSIX-recorded paths.

The candidate helper returns exactly one candidate without checking the
filesystem:

```text
config.LIBRARY_PDFS_DIR / recorded_filename
```

If that exact candidate exists as a file, the resolver returns the candidate.
Otherwise it returns `None`. Missing `source_pdf_path`, an empty string, or
`None` returns `None` from both functions. `None` is the honest error channel.

KNOWN EDGE (for future consumers): campaign_pdf_candidate() returns a candidate
path with NO existence check and NO empty-filename guard. A pathological
recorded path with a trailing separator yields name == '', making the candidate
the pdfs root directory itself. resolve_campaign_pdf() is safe (its is_file()
gate rejects a directory → honest None), but any NEW consumer that calls
campaign_pdf_candidate() directly must not assume the returned path is a file.
The #7 cross-check module is the first likely second consumer — if it uses the
candidate for reporting before checking existence, guard against the empty-name
case there.

## Rationale

This resolver deliberately does not glob, does not use first-match ladders, and
does not reconstruct filenames from ticker plus fiscal year. The recorded
campaign filename is the only source of truth because fiscal years and campaign
names vary per filer.

No-glob resolution avoids live stray-file hazards:

- Agnico duplicate files can look plausible but are not the recorded campaign
  filename.
- MHH live-writer pollution can leave unrelated PDF artifacts near campaign
  files.
- NGEX has dual-name hazards where multiple plausible filenames can exist.
- NFG year mismatch risk means reconstructed `TICKER_FY` names can point at the
  wrong filing year.

## Exclusions

The resolver does not search `_cache/`, `_superseded/`, or `_noncampaign/`.
Because it checks only the root candidate, files that exist only under those
subdirectories resolve to `None`.

The resolver also does not fall back to `~/.finlens/sedar/filings/` or any other
root.

## Out Of Scope

Registry Re-Analyse wiring is a separate follow-on. The dead-end at
`app.py:2374-2382` and sibling `app.py:5595` could later use this resolver, but
wiring it in requires reversing the deliberate `source_pdf_paths intentionally
NOT used` decision at `app.py:917`. That is not part of this build.
