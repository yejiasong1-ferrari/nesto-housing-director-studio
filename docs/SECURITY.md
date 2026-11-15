# Data and publication controls

## Public project page

The public page plays a prerecorded video and displays its recording information. It has no video-upload control, editor, generation endpoint or provider-key input. It does not store visitor media, project data or credentials in browser storage, and makes no model-provider requests.

Footage input and processing belong to a separately configured private Studio, backend and worker. The public page does not connect to that deployment.

## Private generation service

Provider credentials belong in server-side environment variables. Keep `.env`, runtime workspaces, logs, uploaded footage, database exports and cloud credentials outside Git. Do not put provider keys in `NEXT_PUBLIC_*` variables, frontend bundles, project JSON, browser storage or screenshots.

The included FastAPI/worker/Next.js system requires your own access controls, provider configuration, storage settings and deployment review before handling private customer footage. A successful health check alone does not verify these controls or provider availability.

## Publication scan

Run from the repository root:

```bash
python tools/privacy_check.py
```

To compare against actual values from your private environment, add `--private-env` with the local environment file path. The values remain in the scanner process; output includes only a category, a file path and a line number. Never commit that private environment file or a copy of its contents.

The scanner covers the working tree and reachable Git blobs. It checks known credential shapes, private-key blocks, home paths, phone numbers, non-placeholder emails, and optional exact private-value matches. This is a publication check rather than a guarantee: review video frames, audio, document metadata, free-form content and third-party usage rights separately.

## If a credential is exposed

Revoke or rotate it with the provider first. Remove it from current files and reachable history, review the provider's access logs, and invalidate affected sessions. Deleting a file in a later commit does not remove an earlier public copy.
