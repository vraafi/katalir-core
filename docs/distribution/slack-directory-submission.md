# Slack App Directory Submission

Accessed 25 September 2026. Official source: https://api.slack.com/start/distributing/your-app

## Agent-verified

- Public Distribution is enabled per user confirmation.
- Production callback is the Railway backend callback configured in the Slack app.
- OAuth scopes remain minimal: `chat:write`, `channels:read`, `users:read`.
- `/settings` provides full-page Connect Slack flow and connected-state display.
- Logo source and app metadata are available in the repository.

## Required before submit

- 512×512 app icon.
- Three to five product screenshots showing Connect Slack, connected state, workflow execution, and settings.
- Short and long descriptions, category, support URL, privacy policy, and terms URLs.
- Verified redirect URI in Slack OAuth settings.
- Test install in a clean workspace and capture the result.

- Slack official distribution guidance (accessed 2026-09-25) is dashboard/form-based; no documented API for submitting the App Directory application or submitting external review was found. Keep the public-distribution config and screenshots ready for the user submission.

Submit the App Directory form in Slack and complete any review requests. Typical review is several business days; the timeline is controlled by Slack and cannot be enabled by application code.
