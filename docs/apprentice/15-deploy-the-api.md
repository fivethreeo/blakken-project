# 15. Deploying the API is another step

After [mobile publication](14-what-published-means.md), the menu-delete
conversation continued:

> deploy blakken api

This request changed the running server, not the installed apps.

Before deployment, the new menu DELETE route was absent on the live API.
The published app could contain the button while the server still returned
404. That is why a server-backed feature needs both sides released.

## What the established deployment uses

The current environment is Sugar. The application repository is this checkout;
deployment uses the sibling `ansible-home-cluster` checkout and protected
Blakken configuration under `~/.config/home-cluster/`.

The existing procedure builds the frontend and enabled TypeScript backends
locally, then runs the Ansible code deployment. The playbook handles server
code, PostgreSQL migrations, static collection, and services.

The AI should use that procedure, not replace it with an improvised SSH copy
or an AWS/ECS deployment. ECS was discussed as a possible future hosting stack;
it is not what "deploy blakken api" meant in this conversation.

## A short request can still meet a real blocker

For the menu-delete deployment, web/TypeScript builds and syntax checks passed
and a fresh backup completed. Cloud credentials had expired. The user refreshed
them, confirmed the active identity, and the deployment continued.

The response should make a blocker visible when it matters. A short request
does not authorize guessing an identity or asking you to paste secret values
into the chat.

The task reused existing backup resources rather than reprovisioning cloud
infrastructure during an app update.

## Preserve what was just published

Sugar's static storage includes app downloads. The private setting
`app_collectstatic_clear: false` preserves them during static collection.
Clearing that storage casually can break APK/IPA downloads while the web page
still appears healthy.

The AI needs to understand this relationship. You should not have to repeat
"don't erase the apps" every time the known playbook runs.

## Commands are available when you need to inspect them

The root README's **Runtime configuration and production** section contains
the exact build and Ansible invocation. The private files and sibling checkout
are operational dependencies, not material to paste into public docs.

For a new target, name the environment in the short request. If "deploy" has
no clear target, the AI must resolve that before mutating anything. Within
the established Sugar task, the target and procedure carry forward.

Next: [Read the deployment result](16-read-the-deployment.md).
