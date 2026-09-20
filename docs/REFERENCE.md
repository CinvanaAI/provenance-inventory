# Provenance Inventory

A read-only, allowlisted file census that records full SHA-256 provenance evidence without copying, renaming, normalizing, or following indirections into the source tree.

It was extracted from a personal-intelligence dashboard because the inventory engine is useful on its own: before deduplicating, migrating, indexing, or analyzing a messy archive, establish exactly what exists and prove which files are byte-identical.

## Evidence recorded

For every readable file:

- configured source ID and label;
- original and source-relative path;
- size and filesystem timestamps;
- full SHA-256 hash;
- MIME hint and native-medium class;
- project-marker detection;
- scanner version and immutable run ID.

Each completed run contains an append-only JSONL manifest, structured errors, exact-duplicate groups, a summary, and an atomic `latest.json` pointer.

## Safety model

- Only explicitly configured absolute source directories are visited.
- Sources are opened for reading only.
- Symlinks and Windows junctions are skipped.
- Hidden files and exclude globs are caller-controlled.
- A source cannot be the tool checkout or contain it.
- Output cannot be a source or live beneath one.
- Drive roots and the current home directory are rejected as output targets.
- A file changed during hashing is recorded as an error rather than accepted with uncertain evidence.
- Duplicate hashes are candidates for review, never deletion instructions.

## Quick start

Requires Python 3.11 or newer and uses only the standard library.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
Copy-Item examples\sources.example.json sources.json
# Edit sources.json with the exact read-only roots you authorize.
provenance-inventory --config sources.json --output inventory-output
```

Keep `sources.json` and generated inventories private when paths or filenames are sensitive. Both are ignored by Git.

## Output

```text
inventory-output/
  latest.json
  <timestamp-and-run-id>/
    run.json
    summary.json
    manifest.jsonl
    errors.jsonl
    duplicates.json
```

## Development

```powershell
python -W error::ResourceWarning -m pytest -q
python -m pip wheel . --no-deps --no-build-isolation --no-cache-dir -w dist
```

The synthetic tests verify source immutability, full-hash duplicate grouping, project markers, output containment, code-root protection, hidden/exclude policies, and indirection skipping.

See [ORIGIN.md](../ORIGIN.md) and [SECURITY.md](../SECURITY.md).

## Read one run before making a decision

Run `python -m examples.walkthrough` for the disposable three-file example.
`one.txt` and `copy.txt` have equal SHA-256 hashes; `pyproject.toml` is the project
marker. The example compares all source hashes before and after scanning. It
proves read-only behavior for these files, not a filesystem snapshot guarantee.

For your own run, follow `latest.json` to its `summary.json`, then inspect:

| Evidence | Meaning | Decision it cannot make |
| --- | --- | --- |
| `manifest.jsonl` | One readable file, its full hash and source-relative identity per line | Whether a file is useful or disposable |
| `duplicates.json` | Groups sharing an identical full content hash | Which copy to retain, or whether metadata/links matter |
| `errors.jsonl` | Files or traversals that could not supply reliable evidence | Whether the unrecorded content is a duplicate |
| `summary.json` | Counts and completion time for that scan | Whether every source was successfully read |

`status: complete` means the scan finished; check `error_count` before treating
its census as complete evidence. A missing file can be excluded, hidden, an
indirection, or an error. Size and modification-time checks catch ordinary edits
during hashing; this is not a locked snapshot against concurrent or adversarial
rewrites. Stop writers or use an independently created snapshot when stronger
consistency is needed.

Set `include_hidden` to the JSON boolean `false` to omit dot-prefixed path
components. Strings such as `"false"` are rejected instead of interpreted as true.
This setting concerns dot names, not the Windows hidden attribute. Exclude globs
match file names or source-relative paths; an excluded directory is not entered.
Keep every real manifest private until its names and paths have been reviewed.
