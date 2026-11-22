# 16. Read the deployment result

[Asking to deploy](15-deploy-the-api.md) is not the end. Read what actually
happened on the server.

The menu-delete deployment finished with zero failed Ansible tasks. The AI
then checked the relevant services, the API route, and the already-published
mobile downloads.

## What the route check proved

The new DELETE route returned 401 for an unauthenticated request after
deployment. Before deployment it had returned 404.

That showed the route existed and required authentication. No live menu had
to be deleted to obtain this evidence.

It did not prove a signed-in staff member could complete deletion or that
the default-menu fallback looked right on the phone. Those were different
checks, covered by server tests and an approved test-tenant interaction.

When reading a result, distinguish those claims. "Endpoint present" is not
the same as "all user behavior tested."

## The processes in this environment

The established services are:

```text
gunicorn-blakken
celery-blakken
typescript-backend-blakken
typescript-ws-backend-blakken
```

The AI should inspect active state and relevant logs using configured access.
A running worker alone does not prove a task can reach the broker. A healthy
socket server alone does not prove a customer subscription updates the UI.

The checks should follow the actual change, not merely collect green process
names.

## Preserve existing behavior

After deployment, public APK/IPA and SideStore URLs should still work. The
restaurant's shop state and verification policy should not have changed as
an accidental side effect.

The actual check also encountered a localized Norwegian authentication error.
Expecting an English sentence was too narrow; status and stable JSON meaning
were the useful evidence.

The same idea applies to your visual requests. Judge the intended behavior,
not an incidental detail that happened to appear in one environment.

## When something is unfinished

If a deployment fails partway through, the AI should identify what already
changed. "Command failed" does not necessarily mean the server is untouched.
If a device check was not possible, the report should say so.

A short follow-up example is:

> what is left?

or, after a known interruption:

> continue

In context, that continues the same work. It does not mean switch target,
reverse migrations, or replace backups without checking the consequences.

Next: [Stay useful when a task gets interrupted](17-when-work-stops.md).
