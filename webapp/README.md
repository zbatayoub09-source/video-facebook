# Video Facebook — Web application

This folder is the separate web-app layer. The original desktop publisher
(`../publish.py`) is intentionally left unchanged.

## Intended user flow

1. A person registers their own account.
2. They connect their own Meta account and choose a Facebook Page.
3. They upload their own CSV file(s).
4. The server publishes videos for that account and stores a separate
   checkpoint and job history for that account.

## Security requirements

- Never commit real Meta tokens, passwords, encryption keys, uploaded CSVs,
  videos, or database files.
- Serve the app only over HTTPS.
- Store password hashes, never plaintext passwords.
- Encrypt Meta access tokens at rest using a server-side key.
- Enforce account ownership on every upload, job, checkpoint, and log query.
- Do not use a shared/global checkpoint file for multiple users.
- Keep each user's uploaded files in a private per-user storage area.
- Do not expose tokens in HTML, JavaScript, logs, or API responses.

## Meta setup still required

A real multi-user deployment needs a Meta developer app, the relevant
Facebook Login and Page permissions, valid OAuth redirect URLs, and any
Meta review/business verification required for the intended users and use.
The app must not promise publishing access until Meta grants those permissions.

## Current implementation status

The FastAPI scaffold has account registration/login, password hashing,
encrypted storage for a manually supplied Meta user token, private per-user CSV
uploads, and a dashboard. It can now fetch the user's Facebook Pages, encrypt
Page access tokens on the server, and let the user select one Page. Page tokens
are not returned in the page list. The original desktop script remains unchanged.

This is still a development scaffold: the selected Page is saved, but video
publishing is not implemented or enabled.

The repository now includes a Dockerfile and a Render Blueprint
(`../render.yaml`) with a persistent data disk and generated server secrets.
These files prepare deployment; they do not create a live website by themselves.

Still required before public launch:
- Meta OAuth login (the current token-entry method is temporary).
- A per-user publishing worker using the original publisher's behavior without
  sharing its global token or checkpoint.
- Per-user job progress, history, pause/resume, and safe error reporting.
- Production database/storage review, abuse protections, and end-to-end tests.
- Deploy and verify the service on a hosting account.

**Do not share a public link as a finished publisher until these items are
implemented and tested.**

## Local development

Install `requirements.txt`, set the environment variables shown in
`.env.example`, then run:

```bash
uvicorn app:app --reload
```

For local HTTP development, set `COOKIE_SECURE=false`. Use HTTPS and
`COOKIE_SECURE=true` in production.
