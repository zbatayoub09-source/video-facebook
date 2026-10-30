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

## Deployment status

Scaffold only. This is not yet a working public publisher. Authentication,
OAuth, isolated job execution, persistent production storage, and deployment
must be implemented and tested before sharing a public link.

## Local development

Create a virtual environment, install `requirements.txt`, configure the
environment variables from `.env.example`, then run the FastAPI application
once its entry point has been implemented.
