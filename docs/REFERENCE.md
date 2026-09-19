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
