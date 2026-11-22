# 11. Let the AI do the checking

After [access-sensitive work](10-access-is-not-a-ui-fix.md) or a simple screen
change, the AI should check what it changed. You do not have to append a long
test plan to every prompt.

Your task is to read the outcome and notice what has and has not been proved.

## A useful implementation response

For menu deletion, the response separated three things:

- The feature was implemented on the server and both staff clients.
- Django tenant API tests passed.
- Local native builds were unavailable in that environment, and publication
  had not happened.

That is much more informative than "done." It explains why a GitHub build is
still needed before publishing.

For iOS in particular, Linux cannot run Xcode. The established workflow builds
on macOS. The AI should use that path when a release requires it, not claim
that reading Swift source is equivalent to compiling the app.

## The commands are background knowledge

You can ask the AI to run relevant checks. These are some of the commands it
should find in the project:

| Changed area | Relevant starting point |
| --- | --- |
| Tenant/menu APIs | `python run.py manage test blakken.tests.TenantApiTests` |
| Native API behavior | `python run.py manage test blakken.test_native_apps` |
| Browser build | `python run.py npm run build` |
| HTTP service | `python run.py npm-backend test` |
| WebSocket service | `python run.py npm-ws-backend test` |
| Launcher | `python -m unittest test_run` |
| SideStore publisher | `python -m unittest scripts.test_publish_sidestore_source` |
| This guide | `.venv-docs/bin/python -m mkdocs build --strict` |

Run the checks that cover the actual change. A docs-only change does not need
four app builds. A cart UI build does not prove cross-tenant API authorization.

## Try the thing you asked for

If you asked for the total, inspect the total. If you asked for two distinct
buttons, tap them separately. If you asked for confirmation before deleting,
cancel it as well as confirming it on test data.

An AI can perform automated and environment checks, but a native build cannot
show that an interaction feels right on your phone. Keep missing device checks
visible rather than quietly treating compilation as complete UX validation.

## What to say when the response is unclear

Short example follow-ups:

> did both builds pass?

> did you test cancel?

> what is still untested?

These are examples, not prescribed wording. Ask the missing question, then
continue the same task. If a check failed, let the AI resolve that failure
before publication instead of accepting an older build as the new fix.

Next: [Source ready is not release ready](12-before-you-say-publish.md).
