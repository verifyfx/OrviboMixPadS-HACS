# Release process

The origin is `https://github.com/verifyfx/OrviboMixPadS-HACS.git`. Pushing a
version tag publishes a GitHub release after all validation jobs pass. Review
the source and release notes before pushing the tag.

1. Review the complete diff and ensure only generic source, synthetic fixtures,
   docs, original brand assets and CI files are included. Check staged files
   for secrets and private source references.
2. Set a repository description and topics (for example `home-assistant`,
   `hacs`, `orvibo`, `mixpad-s`) in GitHub. They are remote metadata, so the
   custom-repository validation currently ignores those two checks.
3. Run local tests. After an authorized push, inspect **all** CI jobs: offline
   tests/lint/package, real HA tests, hassfest and HACS. Resolve failures.
4. Perform the hardware follow-up in `docs/PROTOCOL.md` with explicit permission.
   For an experimental release, clearly disclose untested behavior in notes.
5. Run `python scripts/project.py version 0.1.0` (or the next x.y.z), update
   `CHANGELOG.md`, review and commit. Versions permit no leading zeros or suffixes.
6. After publication authorization, push the reviewed branch and matching tag
   `v0.1.0`. Do not force-push. The tag workflow reruns validation and checks
   exact agreement between tag and manifest before packaging.
7. The release job uses GitHub's `gh release create --verify-tag --generate-notes`
   with `docs/RELEASE_NOTES.md` to publish the release with `orvibo_mixpad.zip`
   and `SHA256SUMS`. Confirm both assets appear on the public release page.

The ZIP contains integration files at its root, which HACS installs into
`custom_components/orvibo_mixpad/`. `hacs.json` selects that asset. The build
uses an explicit file allowlist and reproducible timestamps; bytecode, tests,
local caches and household data cannot enter via a broad directory ZIP.
Both the integration ZIP and source archives retain the MIT license and
upstream attribution notices.

Workflow permissions default to `contents: read`; only the release job has
`contents: write`. It uses GitHub's job token, with no ORVIBO account secrets.
Pull request validation never creates a release. Release API behavior follows
[GitHub's release documentation](https://docs.github.com/en/rest/releases/releases#create-a-release).
