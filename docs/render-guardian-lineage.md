# Render Guardian lineage

Every governed run records:

- `lineage_id`, `parent_run_id`, `ancestor_hash`
- dataset / split hash
- teacher model + prompt version
- student config hash
- code commit
- trust decision + hard-fail reasons
- release manifest checksum

Split safety: no workspace-session leakage across train/test; before/after pairs stay together; teacher derivatives cannot cross splits.
