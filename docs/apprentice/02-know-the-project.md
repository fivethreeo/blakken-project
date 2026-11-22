# 2. Know what you are looking at

In [the working style](01-how-this-work-feels.md), you start with the thing you
want changed. You still need to recognize which application you are using.

There are three things you commonly look at:

| What you are using | What it is for |
| --- | --- |
| Blakken web/Django admin | Server-backed pages, restaurant data, administration |
| Blakken Management app | Staff menus, orders, restaurant selection, shop state |
| Maharaja app | Customer menu, basket, ordering, order status |

Both mobile apps exist on iOS and Android. They are separate native
implementations, not the same webpage packaged twice.

## What sits behind them

Django owns the application data and the main API. The browser frontend is
built with Rsbuild. There are separate TypeScript HTTP and WebSocket services,
and Celery runs background work.

The WebSocket service is relevant when a screen should update without a manual
refresh. The Django API is relevant when a change saves or deletes data.
The native app matters when a button looks wrong only on a phone.

You do not need to tell the AI all of this every time. These are the landmarks
that help you understand its findings.

## Where the code lives

| Directory | What the AI will usually inspect |
| --- | --- |
| `django-project/blakken/` | Models, API, URLs, templates, tasks, tests |
| `typescript-frontend/src/` | Browser code and styles |
| `typescript-backend/src/` | Node HTTP service |
| `typescript-ws-backend/src/` | Live connections and subscriptions |
| `management-apps/ios/` and `management-apps/android/` | Staff clients |
| `restaurant-apps/maharaja/ios/` and `android/` | Customer clients |
| `.github/workflows/` | Native build recipes |
| `scripts/publish_sidestore_source.py` | iOS publication helper |

Files under `dist/` are built output. If an AI proposes editing them instead of
the source, check why. A generated change may disappear at the next build.

## One feature can cross several parts

Adding menu deletion was not only adding a button. The server needed an
authorized delete route. Both staff apps needed a way to invoke it. Publication
put those apps on phones; deployment put the route on the server.

Separating two toolbar actions, on the other hand, was an iOS screen change.
Android already looked separate. That did not call for a new server endpoint.

This is enough architecture to begin: know who is using the screen, which
platform it is on, and whether you are changing display, stored data, or live
behavior.

Next: [Get something you can look at](03-get-it-running.md).
