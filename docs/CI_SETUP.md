# Enabling GitHub Actions

The tested workflow is prepared in [github-actions.yml](ci/github-actions.yml).
GitHub rejected its initial installation because the publishing OAuth login lacks
the `workflow` scope. The app source is published; automated checks are not yet
enabled on the public repository. Local test results are in [validation](VALIDATION.md).

A repository owner with workflow-write permission can copy that file to
`.github/workflows/ci.yml` and commit it. Alternatively, authorize the publishing
CLI with GitHub's `workflow` scope and push the prepared workflow commit. Never
put a GitHub token in a workflow or commit it to this repository.

The workflow runs Python lint and unit/PostgreSQL integration tests using a
disposable PostgreSQL 16 service, plus Node 22 production build, TypeScript,
unit and Chromium browser tests. It has read-only repository permissions and
requires no provider credentials. A test that requires a locally bootstrapped
Hermes checkout skips when that runtime is absent; live provider acceptance is
separate. Check the first actual Actions run before claiming hosted CI passed.

After checks run successfully, protect `main` with the `python` and `web` checks
if the repository's GitHub plan supports that setting. Use a feature branch and
reviewable commits for each subsequent change.
