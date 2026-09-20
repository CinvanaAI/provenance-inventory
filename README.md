# Provenance Inventory

Establish what files exist and which are byte-identical before deciding how to migrate, deduplicate, or index an archive.

## See it work

**Input:** Three synthetic files: two identical notes and a project marker.

**Result:** Three file records, one duplicate pair, one project marker, zero errors, and unchanged source bytes.

[Read the captured output](examples/result.txt) | [Inspect the example](examples/walkthrough.py)

Python 3.11 or newer. From the repository root:

```sh
python -m pip install -e .
python -m examples.walkthrough
```

The example uses synthetic material and runs offline. The captured output comes from executing this example, not a hand-written mockup.

## How it works

An explicit source allowlist controls traversal. The scanner records full SHA-256 hashes and source-relative metadata, skips filesystem indirections, and produces immutable-run manifests and exact-duplicate groups. Output stays outside the source. The example hashes its source before and after scanning.

Implementation: [provenance_inventory/inventory.py](provenance_inventory/inventory.py), [examples/sources.example.json](examples/sources.example.json), [tests/test_inventory.py](tests/test_inventory.py).

## Limits

Duplicate groups are evidence for review, not deletion instructions. Real manifests include paths and timestamps and are not anonymous. Files changing during hashing are reported as errors. Use short or extended paths for deep Windows workspaces.

[Reference and CLI details](docs/REFERENCE.md) | [Origin](ORIGIN.md) | [MIT license](LICENSE.md)
