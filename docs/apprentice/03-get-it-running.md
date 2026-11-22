# 3. Get something you can look at

Once you [recognize the parts](02-know-the-project.md), get the relevant one
running. The usual point is to see and try it, not merely collect successful
terminal output.

A short example prompt is:

> start the web app

In the repository context, the AI can find the launcher and work out the
commands. If you need access from another device, add that fact:

> make it reachable on the lan

The address matters; another device cannot reach a server bound only to
localhost. Tell the AI the address you actually use if it is not known.

## What the local launcher does

The repository's normal setup is:

```sh
python run.py setup
python run.py manage migrate
python run.py parallel
```

The first command installs dependencies. The second prepares a fresh local
database. The third starts Django, Rsbuild, the two TypeScript services, and a
Celery worker.

Django normally serves the page on port 8000. Rsbuild uses 3000, HTTP uses
8001, and WebSockets use 8002. The dev URLs use those ports, not the production
gateway prefixes.

Use the repository wrapper rather than making up a different local stack.
Local application data and the Celery broker default to separate SQLite files.
That is not the production PostgreSQL/RabbitMQ setup.

## A phone needs a reachable server

The API address configured in a mobile build has to work from the phone.
`127.0.0.1` on the phone means the phone itself. A computer's localhost
development page is not automatically accessible to the native app.

The management and Maharaja builds also need the WebSocket address when using
live updates. Maharaja needs its restaurant app ID. Later chapters explain
where those values enter the build.

## The docs are a separate server

The requests made for this site were short too:

> serve docdms at 192.168.1.2

and later:

> stop task

For this checkout, the working docs command was:

```sh
.venv-docs/bin/python -m mkdocs serve --dev-addr 192.168.1.2:8003
```

Port 8003 avoided the application on 8000. The AI checked the docs URL actually
responded, and stopped the server when asked. Serving docs does not deploy them
or start the mobile apps.

Now that something is visible, start with a problem you can point to.
Next: [Say what is wrong](04-say-whats-wrong.md).
