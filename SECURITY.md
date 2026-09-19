# Security and privacy

Inventory manifests reveal filesystem paths, filenames, sizes, timestamps, hashes, and project structure. Treat generated output as sensitive unless it was produced from an intentionally public fixture.

- Keep real `sources.json` files and inventory output outside Git.
- Confirm every allowed source root before running.
- Use a new dedicated output directory that is not inside a source.
- Do not interpret a duplicate hash as authorization to delete either file.
- Review structured errors; unreadable or changing files are gaps in the evidence.
- Use synthetic directories in public defect reports.

The tool deliberately does not follow symlinks or junctions, but normal filesystem permissions remain the primary access boundary.
