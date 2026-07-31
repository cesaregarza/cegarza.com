# cegarza.com contributor notes

This repository is the Wagtail implementation of cegarza.com.

- Run `uv run ruff check .` and `uv run pytest` before publishing changes.
- Keep the `blog` Django app label and migration history stable.
- Keep public visual work aligned with
  `docs/cegarza-public-design-system.md` and `docs/cegarza-style-guide.md`.
- Treat `ops/export_wagtail_bundle.py` as a read-only compatibility tool.
- Never commit migration bundles, media exports, credentials, restriction
  passwords, local databases, or design-direction archives.
- Release automation may update only
  `helm/cegarza-blog/values-cegarza.yaml` in the GitOps repository.
- Production database and media operations require a backup receipt,
  idempotence proof, and explicit post-operation verification.
