# Data and publication controls

## Public workspace

The static Production Studio makes no model-provider requests. It imports video into browser-local IndexedDB, edits structured scene data, and can export JSON, subtitles and a video rendered on the device. Browser storage is not an encrypted vault and may be cleared by the browser; retain your own footage and exports.

Imported project JSON is mapped to an explicit schema. Remote media URLs, file paths, credentials and arbitrary properties are discarded. User-provided text is escaped before it is displayed. Project narration and brief fields are content fields: do not paste secrets into them.

The connection checker accepts an HTTP(S) base URL without credentials, query parameters or fragments, keeps it in memory only, and makes a credential-free health request when selected. It does not authenticate generation jobs or upload media.

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
