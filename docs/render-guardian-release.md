# Render Guardian release

Promoted artifacts are written under `releases/render_guardian/` as manifests with checksums.

- Large weights are **not** committed to ordinary Git history
- `weights_committed_to_git` must remain false
- JoyView consumes only `release_status=promoted` manifests
- Discarded candidates keep rollback target `incumbent`

## Local 5090 notes

Use `make render-guardian-env-check` before full train. Smoke/dry-run works without CUDA.
