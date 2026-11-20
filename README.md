# blakken-project

A starter with Django, an Rsbuild TypeScript frontend, HTTP and WebSocket
backends, and Celery. The frontend includes only Every Layout styling and
initialization, a JavaScript-availability marker, and an optional docs navigation
toggle. Django serves a minimal HTML shell with an empty `#root` element.

django-filer and easy-thumbnails remain available in Django admin. The icon
sources, generator, and automatic icon build are retained. The editor,
playground, Pages app, custom styles, fonts, and decorative images are removed.

## Native app builds

In GitHub, open **Actions**, select **Build Management iOS**, **Build Management
Android**, **Build Maharaja iOS**, or **Build Maharaja Android**, then choose
**Run workflow**. Download the build from the completed run's artifacts:
iOS workflows provide unsigned device `.ipa` files for SideStore to sign during
installation, and Android workflows provide debug APKs. Each workflow asks for
an API base URL reachable from the device; the Maharaja workflows also ask for
the restaurant's public app ID.

### Native app verification (required by default)

Customer and management apps support **Apple App Attest** on iOS and **Google
Play Integrity (Standard API)** on Android. Both providers can run together on
the same multi-tenant Django deployment. Each platform supplies only its own
proof: an iPhone does not need Google verification, and Android does not need
Apple verification.

Verification is **required by default**, independently of whether trusted app
identities have been configured yet. Customer orders and management API
login/refresh fail closed if verification cannot complete. Missing settings,
disabled app configurations, disabled providers, or outages never automatically
allow unverified requests. Strict clients never fall back to legacy routes.

Native project defaults also require verification. Existing iOS SideStore and
Android debug workflows explicitly opt out for their client builds, but that
does not override server policy: those builds need the corresponding server
opt-out below to submit orders or sign in.

Install the updated Python requirements and apply migrations before activation:

```sh
python3 run.py setup
python3 run.py manage migrate
```

The server environment contains provider-wide switches, the management API
authentication policy, and server-side Google credentials. Defaults are:

```dotenv
DJANGO_APP_ATTEST_ENABLED=true
DJANGO_PLAY_INTEGRITY_ENABLED=true
DJANGO_MANAGEMENT_REQUIRE_APP_VERIFICATION=true
```

#### Enforcement and explicit opt-outs

**Customer orders:** Each restaurant's **Require verified app orders** setting
(`require_verified_orders`) defaults to `true`. Regular/web, SideStore, and debug
orders are rejected with HTTP 403, including retries of saved orders. To
deliberately allow unverified orders for a tenant, uncheck that setting in Django
admin. This is the only customer-order opt-out; deleting or disabling its app
verification settings does not unlock ordering.

**Management API login/refresh:** Verification is required deployment-wide because
the shared management app can access multiple tenants. Explicitly set
`DJANGO_MANAGEMENT_REQUIRE_APP_VERIFICATION=false` to allow legacy management
login/refresh for development, demos, or sideloaded apps. Without that opt-out,
legacy token endpoints return HTTP 403 even when no management app is configured.
This policy does not change Django admin/browser session login.

The migration enables the customer policy for **existing and new restaurants**.
Configure trusted apps and official builds before activating this on a live
deployment, or explicitly opt out for tenants that still need web/sideload orders.
The Maharaja development fixture explicitly opts out of customer verification;
management demo login still needs the separate environment opt-out above.

#### Verification status page

Open **Django admin → Native app registrations → Verification status**, or visit
`/admin/blakken/nativeappregistration/verification-status/`. The page shows
customer ordering and management authentication policies, missing app settings,
provider switches, certificate-digest checks, and actionable Apple/Google setup
steps. Staff need view/change access to both app configurations and restaurants;
starting a credential check additionally requires app-configuration change access.

Loading the page performs local checks only. **Check Google credentials** is an
explicit, CSRF-protected action that discovers the server's Application Default
Credentials and tries to obtain an OAuth token using bounded network requests.
It never displays credentials or tokens, changes policy, or decodes a Play token.
A successful OAuth check does **not** prove Play API enablement or permissions,
Play Console project linking, certificate ownership, correct build configuration,
or a valid real-device verdict. Those remaining steps are listed separately.

#### Configuring app verification per tenant

App verification settings tell the server which official apps to trust. This
is configuration by the operator, not customer sign-up or device enrollment.
In Django admin, create a verification configuration for each official app
(currently labeled **Native app registration** in admin):

| Field | Customer app | Management app |
| --- | --- | --- |
| Platform | `ios` or `android` | `ios` or `android` |
| Role | `customer` | `management` |
| Restaurant | The owning restaurant (required) | Empty (required) |
| App ID | Apple App ID prefix + bundle ID, or Android package name | The management app's own Apple App ID or Android package |
| Certificate digests | Android Play App Signing SHA-256 digests as a JSON list of base64url strings | Same for Android management builds |
| Enabled | Allow this configured app to verify | Allow this configured app to verify |

For example, Maharaja and a second restaurant each have their own customer iOS
and Android verification configurations. The shared Blakken management app has
two additional configurations, one per platform, with no restaurant selected. App identities are
unique per platform; a customer app identity belongs to one restaurant, while a
restaurant can have multiple app verification configurations.

Copy the configuration's public UUID into that build's `APP_REGISTRATION_ID`.
This is **different from `RESTAURANT_APP_ID`**, the restaurant UUID already used
by customer builds. These configuration IDs
are not secrets or authentication credentials. Strict clients send
`X-App-Registration-ID` on challenges, Apple key registration, and protected
requests. The server selects the expected identity from its configuration rather
than trusting an app-supplied identity. Customer requests must match its
restaurant, and the menu must belong to that restaurant.

Challenges and Apple keys are scoped to both app configuration and session. A proof
cannot cross tenants, app configurations, platforms, or customer/management roles.
Disabling a configuration stops new verified operations for that app without
disabling other tenants. Provider switches can disable all apps for one platform.
The regular-order block is based on the restaurant's **Require verified app
orders** policy, not app configuration, provider switches, or credential
availability. Either platform's valid proof can authorize its
restaurant's strict order route; enabling iOS does not require Android proof or
vice versa. Disabling/deleting **all** customer app verification configurations
leaves verified-only ordering enforced. Only explicitly changing the restaurant's
policy permits unverified orders. Management app configurations do not affect
customer ordering policy.

#### Official build configuration

**iOS:** Provision an officially signed app with the App Attest capability and
production entitlement. The configured App ID is the actual Apple App ID
prefix plus bundle ID (the prefix is often, but not always, the Team ID).
Entitlement templates are provided at
`restaurant-apps/maharaja/ios/AppAttest.production.entitlements` and
`management-apps/ios/AppAttest.production.entitlements`. A separate official
signing configuration must set `CODE_SIGN_ENTITLEMENTS` to the appropriate file,
`INFOPLIST_KEY_APP_ATTEST_REQUIRED=YES`, and
`INFOPLIST_KEY_APP_REGISTRATION_ID=<configuration-uuid>`. Strict clients require
HTTPS. These settings are intentionally not enabled in the SideStore workflows.
The server verifies Apple's certificate chain, production environment,
official-app validation claims, assertion signatures, and counters. Unsupported
devices and sideloaded/re-signed builds are not accepted by this strict policy.

**Android:** Link the Play Console app to a Google Cloud project, enable the
Play Integrity API, and configure server-side Application Default Credentials
for a service account with access to decode tokens in that linked project.
All Android app configurations use the deployment's ADC; its credentials must have
access to verify the configured apps. Keep credentials outside Git and APKs.
Store the **Play App Signing** certificate's SHA-256 digest (not the upload/debug
certificate) as base64url, not colon-separated hexadecimal, in each app's configured
JSON list, for example `["base64url-digest"]`. Add rotated certificates to that
list. A separate Play-distributed customer or management build must set Gradle properties
`PLAY_INTEGRITY_REQUIRED=true` and
`PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER=<linked-project-number>`, plus
`APP_REGISTRATION_ID=<configuration-uuid>` and `BLAKKEN_API_BASE_URL`. Customer
builds also need `MAHARAJA_APP_ID`; management builds retain
`BLAKKEN_WS_BASE_URL` for live updates. The strict client requires HTTPS.
The server requires matching package, certificate, and request hash, a fresh
token, `PLAY_RECOGNIZED`, `MEETS_DEVICE_INTEGRITY`, and `LICENSED`; ordinary
sideloaded debug APKs do not satisfy this policy.

#### Protected operations

All strict flows first establish a session using `GET /api/v1/customer/session/`
and retain its cookies and CSRF token. The response includes an opaque
`attestation_session` fingerprint so iOS key caching also distinguishes session
resets. Single-use, five-minute challenges bind proofs to the exact request body.
Customer proofs also bind the restaurant/menu; management proofs bind the
app configuration and login/refresh operation. Missing or invalid proofs are rejected
with HTTP 401; disabled/unavailable app configurations or providers return HTTP 503.
Wrong customer-restaurant bindings return HTTP 404. CSRF protection still applies.
Regular order requests to a restaurant whose policy requires app verification
return HTTP 403 with code `app_verification_required`. Sending configuration ID or
proof headers to a regular order route does not authorize it; verification must
complete successfully through the appropriate strict endpoint.

| Platform | Challenge / Apple key setup endpoints (POST) | Strict order endpoint (POST) |
| --- | --- | --- |
| iOS | `/api/v1/official/app-attest/challenges/`, `/api/v1/official/app-attest/keys/` | `/api/v1/official/restaurants/<appid>/menus/<menu_id>/orders/` |
| Android | `/api/v1/official/android/play-integrity/challenges/` | `/api/v1/official/android/restaurants/<appid>/menus/<menu_id>/orders/` |

Official management apps use the same platform-specific challenge/key routes,
then send their proof with credentials to
`POST /api/v1/official/management/<ios|android>/auth/token/`, or with a refresh
token to `POST /api/v1/official/management/<ios|android>/auth/refresh/`.
**Attestation is required on login and refresh, not on every management request.**
Issued access tokens continue to work with the existing management HTTP and
WebSocket APIs. User credentials and restaurant memberships are still required;
attestation never grants access to additional restaurants.

Verified refresh tokens are bound to their management app configuration and cannot
be refreshed through the legacy endpoint or a different app configuration.
Legacy refresh tokens cannot be upgraded through the strict endpoint; sign in
again in the official app. Disabling an app blocks new verified login/refresh,
but already-issued access tokens remain valid until normal expiry. Existing
legacy login and refresh routes are usable only when the management server
policy is explicitly opted out. Even with that opt-out, verified refresh tokens
still cannot use legacy refresh.

Run the backend verification and coexistence regression tests without building
either app:

```sh
python3 run.py manage test blakken.test_app_attest blakken.test_play_integrity blakken.test_native_apps
```

This is prepared integration support, not a configured store release. Official
signing, Google credentials/console setup, and real-device validation are still
required; the existing workflows do not produce verified store builds.

## Maharaja demo data

Load the fictional Maharaja restaurant into a development database with:

```sh
python3 run.py manage loaddata blakken/fixtures/maharaja_demo.json
```

The fixture creates an active restaurant, a sample menu, categories, dishes, and
an owner account named `maharaja-demo@example.test`. The account has no usable
password; set one with `python3 run.py manage changepassword
maharaja-demo@example.test` before signing into a management app. Its restaurant
app ID is `ca7a0000-0000-4000-8000-000000000001`.

Alternatively, restore the current Sugar menu snapshot (9 categories, 17 dishes)
with customer verification explicitly **off**:

```sh
python3 run.py manage loaddata blakken/fixtures/maharaja_current_unverified.json
```

This fixture contains only Maharaja's restaurant, menu, categories, and dishes;
it includes no accounts, passwords, orders, or verification keys. Create an owner
membership separately for a fresh database. Choose one Maharaja fixture, not
both: they share the app ID but use different database primary keys. Loading a
snapshot into an existing database can overwrite matching menu records.

The fixture does not change management authentication. Sugar's private deployment
configuration explicitly sets `app_management_require_app_verification: false`,
which the matching Ansible role writes as
`DJANGO_MANAGEMENT_REQUIRE_APP_VERIFICATION=false`. Other deployments keep the
default-required policy.

## Development

Run the projects present in the checkout with `python run.py parallel`.
`python run.py setup` likewise installs dependencies only for existing project
directories. Remove any of the TypeScript project directories to omit that
component; removing `django-project/` omits both Django and Celery. Django and
its Celery worker always start together in parallel mode.

With all components present, the web services bind to `127.0.0.1` on
ports 8000, 3000, 8001 and 8002 respectively. Override the host and ports, for example:

```sh
python run.py parallel HOST=0.0.0.0 DJANGO_PORT=8100 RSBUILD_PORT=3100 TS_BACKEND_PORT=8101 TS_WS_BACKEND_PORT=8102
```

Rsbuild watches and rebuilds frontend assets; both backends use `tsx watch` to
reload TypeScript and restart on source changes. Django's development server
reloads Python changes. Press Ctrl+C to stop all running services, including their child
processes. If a dev runner exits, the launcher stops the other services and
exits with a failure status.

Dev endpoints use separate ports: Django at `http://127.0.0.1:8000/`, HTTP health
at `http://127.0.0.1:8001/healthz`, and WebSockets at `ws://127.0.0.1:8002/`.
The production Nginx `/api/` and `/ws/` prefixes are not applied in this mode.

The development worker uses a local SQLite broker at
`django-project/celery-broker.sqlite3`; PostgreSQL, RabbitMQ and containers are
not required. Django's application data stays in `django-project/db.sqlite3`
when `DJANGO_DATABASE_NAME` is empty. For a fresh development database, run
`python run.py manage migrate` before starting the stack.

The worker initializes the same Django settings and database as the web server,
so tasks can use the Django ORM for reads and writes. It runs a single-process
solo pool without Beat. Restart `parallel` after changing task definitions;
Celery does not automatically reload them.

SQLite messaging is development-only and does not provide RabbitMQ's event or
remote-control features. Concurrent application database writes can encounter
SQLite locking. Production keeps PostgreSQL/RabbitMQ. Explicit
`CELERY_BROKER_URL` values override the development default; a result backend
remains optional.

In parallel mode, Rsbuild writes development JavaScript assets to disk. When
it completes a successful rebuild, its dev hook sends SIGHUP to `DJANGO_PID`,
which the launcher sets after starting Django first. Django's dev-only signal
handler touches an autoreloader-watched file: the serving child restarts while
the parent PID remains stable. The first compilation and failed builds do not
signal Django. This Unix-only hook is disabled for standalone Rsbuild, Windows
and production builds. Parallel mode requires Django's autoreloader only when
both Django and the frontend are present; Django without frontend accepts
`--noreload`.

Changes to `assets/master_icons.svg` regenerate the hidden SVG sprite collection
at `django-project/blakken/templates/includes/icons.svg` automatically. Django
includes it inline in the page; UI icons can reference symbols with
`<svg aria-hidden="true"><use href="#icon-id"></use></svg>`.
Run `python assets/make_svg_icon_sprites.py` to generate it manually. There is no
TypeScript registry or icon-font output. Both master layers start empty; empty
masters generate an empty sprite without needing Inkscape. Nonempty artwork uses
the existing Inkscape extraction pipeline. In either the Artwork or ViewBoxes
layer, a rectangle defines a viewBox only when its ID exactly matches its
Inkscape label and its ID does not match `rect\d+`. Unchanged output is not rewritten,
and icon watching is skipped when Django, the master SVG, or generator is absent.

Ports for present components must be different and between 1 and 65535;
assignments for absent components are ignored. `HOST` controls where
all services listen; use
`PUBLIC_HOST` when it differs from the address opened in a browser. For
example, to bind on all interfaces while accessing the application from the
local network:

```sh
python run.py parallel HOST=0.0.0.0 PUBLIC_HOST=192.168.1.2
```

`PUBLIC_HOST` is used for Rsbuild asset URLs and the HMR WebSocket. In development,
Django permits CORS from `http://localhost:3000`, `http://127.0.0.1:3000` and the
configured `RSBUILD_BASE_URL` origin (including custom hosts/ports). Production
still requires explicit origins. `parallel` also sets `RSBUILD_CORS_ORIGIN` to
the Django and HTTP TypeScript backend origins derived from `PUBLIC_HOST`,
`DJANGO_PORT`, and `TS_BACKEND_PORT`, allowing frontend assets to load from
port 3000 into pages served by either service.
Override either direction when needed:

```sh
# Override the allowed origins for requests to Django.
python run.py parallel DJANGO_CORS_ALLOWED_ORIGINS=http://localhost:3000

# Override the comma-separated origins allowed to load Rsbuild assets.
python run.py parallel RSBUILD_CORS_ORIGIN=http://localhost:8000,http://localhost:8001
```

An explicit empty `DJANGO_CORS_ALLOWED_ORIGINS` disables Django's dev defaults.
An explicit empty `RSBUILD_CORS_ORIGIN` disables the launcher's Rsbuild CORS default.
Cookie-authenticated cross-origin requests additionally need
`DJANGO_CORS_ALLOW_CREDENTIALS=true`, matching `DJANGO_CSRF_TRUSTED_ORIGINS` and
the normal CSRF token; CORS does not bypass CSRF protection. In parallel mode, use
the environment assignments instead of passing shared `--host`, `--port`, or
`--addrport` arguments. The TypeScript starters do not enable cross-origin HTTP
access automatically.

### Django without frontend

Removing `typescript-frontend/` automatically disables Django's frontend
integration. Its page and admin still work, and `collectstatic` still collects
Django/admin assets without needing a frontend build. Alternatively, set
`DJANGO_FRONTEND_ENABLED=false` to disable asset integration while keeping the
directory. When frontend integration is enabled, a missing manifest still
raises the usual build/dev-server error.

For code deployment, select Django without frontend explicitly:

```yaml
app_django_enabled: true
app_frontend_enabled: false
```

The Ansible code deployment pairs the Celery worker with Django; Beat remains
optional. Deployment component switches remain explicit rather than inferred
from deleted directories. Parallel mode leaves absent backends' generated URLs
empty; explicit URLs for externally hosted services still work.

## Automatic and manual continuation pages

Set the menu-wide **Max dishes per first page** and **Max dishes per extra page**
in admin (defaults: **4 / 5**). Dishes overflow automatically into continuation
pages in their saved order. These are rendered pages, not additional database
records; edit dishes on their original page. Covers are not split. Leave either
limit blank to use manual pages only.

You can also add a menu page in admin, tick **Continuation page**, and position
it after its category and before the back cover. Assign its dishes manually.
Manual continuations use the extra-page limit and can themselves overflow.

Continuation pages keep their decorative feelgood heading and dishes, but omit
the category title, introduction and contents entry. They still have page numbers
and their own URL hash. Reusing the name/slug `Curry` generates collision-safe
slugs such as `curry-to`, `curry-tre`, and `curry-fire`, including when adding
several pages together in the nested admin. Existing hashes are unchanged.
Automatic continuations use the same suffixes and skip hashes reserved by manual
pages. Panorama images span the first pair rather than repeating on every extra
page. Reload the menu after adding/reordering pages or changing limits or dish
counts enough to change the number of rendered pages.

Staff and superusers can move dishes up/down in the book or JavaScript text
view, including across automatic continuation pages. Moves are saved in Django
and refresh the reader in place. Edit opens a page-styled Imposter dialog for
the dish's name, description, optional price and allergens. The editor uses
hand-authored HTML and JSON `GET`/`PATCH` requests to
`/menus/<menu_id>/dishes/<dish_id>/`, not Django forms. The plus beside the large
category heading opens a blank dish, including in empty categories. JSON `GET`
to `/menus/<menu_id>/pages/<page_id>/dishes/` provides the blank fields and
allergen choices; `POST` saves it. The dish editor has no Add button.
`Slett` requires confirmation inside
the editor before sending `DELETE` to the dish endpoint. Creation and deletion
reload the category to rebuild continuation pages and padding. All mutations
require a staff or superuser session and CSRF token. Saving edits refreshes the reader in place;
if the edited content no longer fits the captured page dimensions, it reloads
the book automatically to recalculate its size.

The staff page toolbar uses left/right arrows to move a category together with
its manual and automatic continuations, keeping covers fixed. The top plus
opens a blank page editor and inserts a new category after the current category
and its continuations. The front cover's plus can insert the first category.
The cross requires confirmation before deleting the category, continuation pages
and their dishes; covers cannot be deleted. Page changes reload the book to
rebuild pagination and contents. These actions use staff/superuser and
CSRF-protected REST endpoints: `POST /menus/<menu_id>/pages/`,
`POST /menus/<menu_id>/pages/<page_id>/move/`, and
`DELETE /menus/<menu_id>/pages/<page_id>/`.
Icon buttons have native `title` tooltips, retained by book overlays. All editing
controls remain hidden without JavaScript.
Staff can use the eye icons (**Skjul / Vis**) on pages and dishes to hide them from customers
without deleting them. A page toggle includes its manual and automatic
continuations; covers stay fixed and cannot be toggled in the reader.
Hidden entries remain visible and marked in the staff book for re-enabling.
Customer pagination and contents omit hidden entries, and checkout rejects
hidden dishes and dishes on hidden pages, including from old baskets.
Dish visibility uses the existing JSON `PATCH` endpoint with boolean
`is_visible`; pages use `PATCH /menus/<menu_id>/pages/<page_id>/visibility/`.
Both require staff/superuser access and CSRF. Visibility can also be edited
in the nested Django admin.
Initial hash restoration is immediate, so returning after edits, moves,
additions, deletions or a dimension-rebuild reload does not animate from the
front cover. Normal reader navigation still animates.

## Ordering

The menu opens directly on the book, without an extra heading above it. A fixed
bottom-right cart button opens compact modal checkout without leaving the book.
Guests can add priced dishes, adjust quantities using cartadd/cartremove, remove
a complete row using cross, and submit their name, phone number and optional note.
Brief, nonblocking flash messages explain the controls and confirm basket actions.
Order confirmation stays in a separate order-status modal until it is closed.
Basket contents survive reloads in browser
storage; customer contact details are not stored there. There is no online
payment or phone confirmation yet.

`POST /menus/<menu_id>/orders/` accepts JSON containing `submission_id` (a UUID),
`customer_name`, `phone`, `note`, and `items` (`dish_id` and `quantity` only).
CSRF is required even for guests. Django validates quantities and availability,
calculates prices from the database, and stores names and prices as historical
snapshots. Retrying the same submission ID and payload returns the original
order instead of creating duplicates.

Staff/superusers use `/orders/` (ordinary users cannot access it). Visitors are
redirected to `/orders/login/` to sign in with an existing staff/superuser account.
The toolbar's **Logg ut** button ends the session and returns to the order login.
Staff can use **Steng butikken / Åpne butikken** to persistently close or open
ordering across the shop. The default is open. Visitors get a dismissible
30-second availability notice on entry. Open pages receive a live notice when
the shop closes or reopens, through the public `/shop/?appid=<restaurant-app-id>`
WebSocket channel. Customer iOS and Android apps subscribe to that same
tenant-specific channel, refetch availability on `shop.changed`, and immediately
disable order-entry and basket controls while closed without discarding the
basket or entered details. An in-app alert appears when ordering closes or reopens,
whether the customer is browsing the menu or already in checkout. Controls are
enabled again when ordering reopens. Shop updates do not
require an account, order, or attestation session and never include private order
data. Native clients reconnect and refresh when returning to the foreground;
Android also reconciles every 30 seconds. Updated native builds are required for
devices with older customer apps. Set iOS `TS_WS_BACKEND_URL` or Android
`BLAKKEN_WS_BASE_URL` to the public WebSocket base URL, such as
`wss://blakken.cavabonga.no/ws/`.
Availability is also checked every 30 seconds, on reconnection, and when returning
to the tab. While closed, checkout is disabled
and the server rejects new orders, including from previously opened pages.
Basket contents and existing order management/status updates remain available.
Retries of an already-saved order still return its receipt while closed.
`GET /shop/status/` is public; staff-only, CSRF-protected `PATCH` requires boolean
`is_open` and `expected_is_open` values, rejecting stale changes with HTTP 409.
Active orders are shown by default; the filter also exposes completed/cancelled history, with 25 orders
per page. Statuses progress **new → preparing → ready → completed**;
non-completed orders can be cancelled. Updates check the expected prior status
to prevent staff from overwriting one another.

Live updates reuse the existing session-authenticated WebSocket service:
configure `DJANGO_TS_WS_BACKEND_URL`, `DJANGO_INTERNAL_URL`,
`DJANGO_INTERNAL_AUTH_TOKEN`, `WS_ALLOWED_ORIGINS`, `WS_INTERNAL_URL`, and
`WS_INTERNAL_NOTIFY_TOKEN` as described below. The Django and WS processes must
share the respective service tokens. After a database commit, Django sends an
`orders.changed` hint to active staff users' sockets; no customer details travel
in the event. Delivery is best-effort and does not require a Celery worker.
The dashboard fetches order data through staff-protected HTTP endpoints,
reconnects automatically, and reconciles every 30 seconds to recover missed
events. If WebSockets are unavailable, stored orders remain accessible.

Customers who keep the menu open see a separate order-status modal whenever a known status changes.
If it has been closed, it reopens; an already-open modal updates in place.
All unfinished orders are tracked, including concurrent orders, with a prominent
current status and a short explanation for each. Changed orders are shown first.
Completion and cancellation updates remain visible until the modal is dismissed;
previously finished orders are not shown or replayed. The status API includes all
unfinished orders plus the 25 most recently updated finished orders for reconciliation.
No separate panel is added around the book. The panel survives reloads in the
same browser session; its first load does not replay old popups. A server-side
session channel scopes both `GET /orders/mine/` and the `/orders/` path on the
WebSocket service to that customer's orders. The private WebSocket handshake
uses `/internal/order-auth/` with the existing service token. No channel IDs or
customer contact details are exposed in the browser's status responses.
Reconnection, page visibility changes and 30-second reconciliation recover
missed updates; changes detected after reconnect also trigger the popup.

Apply the schema with `python run.py manage migrate` before accepting orders.

## Refreshing menu content

Django renders the menu pages through `blakken/templates/menu/pages.html`, shared by
the initial page and `GET /menus/<menu_id>/pages/`. The fragment view uses the
current session and disables caching, so future login-dependent controls can be
rendered in that template.

After saving changes or completing login/logout, refresh the initialized reader:

```js
await window.menuReader.refresh();
```

This fetches fresh HTML, replaces the existing articles' content, updates contents
labels, then awaits Turnpage's `rerenderAll()`. Article identities, generated pages,
reading position and click-to-turn settings are preserved. Refreshes are queued;
failed requests leave existing content untouched. Adding, removing, reordering or
changing page layouts/anchors or the contents setting requires a page reload.
Content still needs to fit the book's original capture dimensions.

## Standalone frontend HTML

Edit `typescript-frontend/src/index.html` for a page served without Django.
Rsbuild generates `dist/index.html` and inserts the built CSS and JavaScript
automatically; Django continues to use its own template.

For frontend deployment at `/blakken/` with assets at `/blakken/static/`, build
from the repository root with the matching asset prefix:

```sh
RSBUILD_ASSET_PREFIX=/blakken/static/ python3 run.py npm run build
```

In the Ansible application configuration:

```yaml
app_django_enabled: false
app_frontend_enabled: true
app_frontend_html_location: /blakken/
app_static_location: /blakken/static/
celery_enabled: false
celery_beat_enabled: false
```

HTML serving defaults to enabled when frontend is enabled without Django.
Set `app_frontend_html_enabled: false` for assets only, with HTML hosted
elsewhere. The page location defaults to `app_django_location`; this does not
enable Django. The standalone page has no automatic Django context or backend
URL data attributes, and unknown page paths return 404 rather than an SPA fallback.

To update only frontend on an existing application without restarting its
backends, use the Ansible code playbook with `app_frontend_only_update: true`
and the application's existing configuration. This also enables the built HTML
by default, while retaining nested Django admin, media, API and WebSocket routes.

## Independent TypeScript backends

The repository has four sibling project directories:

```text
django-project/
typescript-frontend/
typescript-backend/
typescript-ws-backend/
```

`typescript-backend` is a Node.js HTTP starter serving JSON at `/` and
`/healthz`. `typescript-ws-backend` serves `/healthz` over HTTP and echoes text
and binary WebSocket messages at `/`. Both require Node 20 or newer and read
`HOST`, `PORT`, and `APP_NAME` from the environment. Defaults are localhost,
ports 8001/8002, and app name `blakken`.

Install and build locally from the repository root:

```sh
python run.py npm-backend ci
python run.py npm-backend run build
python run.py npm-ws-backend ci
python run.py npm-ws-backend run build
```

For development, use `npm-backend run dev` or `npm-ws-backend run dev` through
the wrapper. Append `HOST=127.0.0.1 PORT=8001 APP_NAME=blakken` assignments to
override the environment. Each directory also has its own `.env.example`;
after building, Node's `--env-file=.env` option can load a local file explicitly.
Run `python run.py npm-backend test` and `python run.py npm-ws-backend test` for
the service tests.

Both starters optionally identify users through Django's internal
session-authentication endpoint. HTTP `/` and WebSocket upgrades also support
anonymous clients; `/healthz` remains public. The WebSocket starter limits messages to 1 MB, checks browser
Origin, and uses heartbeats to detect dead connections. Add application-specific
handlers and authorization before using them for private data.

The Ansible code deployment consumes each selected backend's prebuilt `dist`
and lockfile. It installs production Node dependencies but never compiles
TypeScript or runs frontend builds on the server.

### Backend locations in Django pages

Django reads `DJANGO_TS_BACKEND_URL` and `DJANGO_TS_WS_BACKEND_URL` into
`TS_BACKEND_URL` and `TS_WS_BACKEND_URL`. Parallel dev automatically sets
browser-facing URLs using `PUBLIC_HOST` and the backend ports (by default
`http://127.0.0.1:8001/` and `ws://127.0.0.1:8002/`). Explicit environment or
command-line values override these defaults.

Deployment sets the enabled services' public gateway paths, such as `/api/`
and `/ws/`, even when their servers are elsewhere. Disabled services have empty
values; private upstream addresses are never advertised to the browser.

The HTML shell exposes these on `<body>`:

```html
<body data-ts-backend-url="/api/" data-ts-ws-backend-url="/ws/">
```

JavaScript reads `document.body.dataset.tsBackendUrl` and
`document.body.dataset.tsWsBackendUrl`. Resolve relative locations against the
page URL; for WebSockets use `ws:` for HTTP pages and `wss:` for HTTPS pages.
This advertises endpoints only; it does not enable CORS or authentication.

### Internal session authentication

`GET /internal/auth/` validates a Django session for a trusted backend.
Set `DJANGO_INTERNAL_AUTH_TOKEN` to a server-only shared token. The caller
sends `Authorization: Bearer <token>` and the browser's Django session cookie.
Success returns `{"user_id": ...}`; invalid service credentials return 403,
an invalid session returns 401, and an unset token disables the endpoint with
503 and logs a startup warning. Responses must not be cached.

Both TypeScript backends call this endpoint; they do not decode or validate
sessions locally. Set the same `DJANGO_INTERNAL_AUTH_TOKEN` in the environment
of Django and both Node processes, and set their server-only
`DJANGO_INTERNAL_URL` to Django's internal base URL (include any gateway mount
prefix). A token in Django's `.env` alone is not passed to Node by the launcher.
Missing/invalid sessions, no token, an unreachable auth endpoint, or an
unusable response fall back to anonymous access (`userId: null`); calls time
out after three seconds. Only a valid Django response supplies a user ID.
Each Node backend warns once at startup if its auth token or internal Django
URL is missing, disables session authentication, and retains anonymous access.
If multiple Django apps share a browser origin, give each a distinct
`DJANGO_SESSION_COOKIE_NAME` and `DJANGO_CSRF_COOKIE_NAME`, with
`DJANGO_SESSION_COOKIE_PATH` and `DJANGO_CSRF_COOKIE_PATH` scoped to its mount.
Set the same session cookie name in both Node environments; only that named
cookie is forwarded to Django. Defaults remain `sessionid`, `csrftoken`, and `/`.
Use `DJANGO_STATIC_URL` and `DJANGO_MEDIA_URL` for namespaced public asset/media
paths, and set `RSBUILD_BASE_URL` to the public static prefix without its trailing
slash. Configure the gateway to serve these prefixes from the app's own roots.

`parallel` supplies the internal URL from its bind host and Django port,
using loopback for wildcard binds. It also supplies `WS_ALLOWED_ORIGINS` from
the public Django, HTTP backend, and Rsbuild origins. Explicit environment or
command-line values override these defaults. Standalone WS deployments must
configure an exact comma-separated Origin allowlist; absent or unlisted
origins are rejected. Only the session cookie is forwarded, not other browser
cookies or the browser's Authorization header.

Keep the auth route private at the gateway and use HTTPS between machines.
HTTP `/` requests and WS connections have a `userId` property, which is null
for anonymous clients. Require a non-null ID for user-specific operations
and subscription authorization; never trust a browser-supplied ID. WS identity
is checked at upgrade only; logout does not disconnect connections automatically. HTTP CORS is
not enabled by these starters; use a same-origin gateway or configure
credentialed CORS separately for cross-origin browser requests.

### Job records and bulk results

`blakken.models.Job` records a user, unique Celery task ID, and creation time.
Records are not created automatically: after submitting a task, save its ID
with `Job.objects.create(user=request.user, task_id=task.id)`. Run
`python run.py manage migrate` to create the table.

`GET /jobs/results/?page=1` returns only the logged-in user's jobs, newest
first, in pages of 25. Authenticate using the Django session cookie. The
response contains `count`, `page`, `pages`, and `results`; each result includes
the job ID, task ID, creation time, Celery status, and a JSON-compatible result
for successful tasks. Other statuses have a null result; exception details
and tracebacks are not returned.

Configure `CELERY_RESULT_BACKEND` to retrieve results, for example
`db+sqlite:///celery-results.sqlite3` for local development. Missing/unavailable
result storage returns 503 for nonempty pages. Unknown or expired task results
can appear as `PENDING`. The endpoint batches results into one HTTP response,
but looks up each task separately in the Celery backend.

### Internal WebSocket notifications

`POST /internal/notify/` on the WS backend accepts JSON such as
`{"user_id": 42, "event": "addition.finished", "result": 5}`.
Set `WS_INTERNAL_NOTIFY_TOKEN` in the WS process and trusted sender's
environment, and send it as `Authorization: Bearer <token>`. This token is
separate from Django's internal auth token; an empty value disables the route
with 503 and logs one warning when the WS backend starts. Keep the route private
at the gateway and use HTTPS between machines.

Bodies are limited to 64 KiB. Invalid JSON/notification fields return 400,
invalid credentials return 403, and oversized bodies return 413. Each open
connection with the matching Django-validated user ID receives
`{"event": "addition.finished", "result": 5}`. Other users and anonymous clients
do not receive it.

The response is `202 {"matched_connections": ...}`, including zero when the
user is offline. This counts matched sockets, not browser acknowledgements.
Notifications are not persisted or deduplicated; retries can deliver duplicates.

`blakken.tasks.notify(result, user_id, event='task.finished')` is a Celery
sender task. Configure `WS_INTERNAL_URL` as the private WS HTTP base URL,
for example `http://127.0.0.1:8002/`, and set the same
`WS_INTERNAL_NOTIFY_TOKEN` in Django/Celery and the WS process. `parallel`
supplies the private URL using the configured WS port; it does not generate
or copy a token from Django's `.env` into Node.

```python
from celery import chain
from blakken.tasks import notify

# work is your existing Celery task; its result becomes notify's first argument.
chain(work.s(), notify.s(request.user.pk, 'work.finished')).apply_async()
```

Only successful work triggers the notification. The sender returns the original
result and accepts HTTP 202 even when no sockets are connected. Network failures,
HTTP 429 and HTTP 5xx retry up to five times with exponential delays; redirects,
other HTTP failures and invalid/oversized payloads do not retry. Redirects and
environment proxies are disabled so private service credentials stay on the
configured destination. Missing URL/token disables delivery, returns the original
result, and logs a startup warning rather than warning for every task.

Ansible forwards this private URL and token to Django/Celery and the TS HTTP
backend when WS is enabled. These values are server-only and are not added to
the frontend or page data attributes. The HTTP starter does not send notifications
automatically.

## Runtime configuration and production

Copy `django-project/.env.example` to `django-project/.env` for local settings.
Alternatively set `DJANGO_ENV_FILE` to a protected file outside the checkout.
Existing process environment variables take precedence over `.env`; values are
not interpolated, so credentials containing `${...}` are preserved literally.
Do not commit `.env` files or production credentials.

Development keeps SQLite unless a database name is configured. Production
(`DJANGO_DEBUG=false`) requires `DJANGO_SECRET_KEY` and
`DJANGO_DATABASE_NAME`. A configured database defaults to PostgreSQL; set
`DJANGO_DATABASE_USER`, `DJANGO_DATABASE_PASSWORD`, `DJANGO_DATABASE_HOST`,
and `DJANGO_DATABASE_PORT`. Legacy `DATABASE_*` names remain accepted, with
`DJANGO_DATABASE_*` taking precedence.

Set `DJANGO_STATIC_ROOT` and `DJANGO_MEDIA_ROOT` to persistent paths outside
the code checkout. Production upload permissions default to `0640` for files
and `2750` for directories, suitable for an app-owned directory shared with
Nginx through its group. Enable `DJANGO_TRUST_PROXY_HEADERS` only behind a
trusted proxy; secure-cookie settings can be enabled independently for HTTPS.

Memcached is optional. Set `DJANGO_MEMCACHED_LOCATION=127.0.0.1:11211` to use
Django's `PyMemcacheCache` backend, with one-second connection/read timeouts.
Leave it empty to retain Django's local-memory cache. Set
`DJANGO_CACHE_KEY_PREFIX` to a distinct deployment name, such as `blakken` or
`blakken_staging`, when sharing a cache server. Code accesses it through
`django.core.cache.cache`; this does not automatically cache views or sessions.
Keep Memcached private and treat its data as disposable, not persistent storage.

Celery uses `blakken` as its app and autodiscovers `tasks.py` in installed
Django apps. Configure `CELERY_BROKER_URL` with your RabbitMQ user/vhost and,
if needed, `CELERY_RESULT_BACKEND`:

```sh
cd django-project
DJANGO_ENV_FILE=/path/to/runtime.env .venv/bin/celery -A blakken worker --loglevel=INFO
DJANGO_ENV_FILE=/path/to/runtime.env .venv/bin/celery -A blakken beat --loglevel=INFO \
  --schedule=/path/to/persistent/celerybeat-schedule
```

Run only one Beat instance per application schedule. For production, use
Gunicorn (`blakken.wsgi:application`) and systemd rather than development
servers.

Build the frontend on your workstation before deployment. The matching
`ansible-home-cluster/deploy-app/deploy-code.yml` uploads this checkout's Django
source and prebuilt frontend output, writes Vault-backed settings, runs
PostgreSQL migrations and `collectstatic`, and manages Gunicorn/Celery.
It does not run the frontend build on the deployment host.

The production deployment uses a separate `blakken.yml` and encrypted
`blakken-secrets.yml` in `~/.config/home-cluster/`; keep both outside Git. Build
the frontend and enabled TypeScript services locally, then run
the deployment from this checkout:

```sh
python3 run.py npm ci
python3 run.py npm run build
python3 run.py npm-backend ci
python3 run.py npm-backend run build
python3 run.py npm-ws-backend ci
python3 run.py npm-ws-backend run build
ansible-playbook -i ../ansible-home-cluster/provision-hosts/inventory.yml \
  ../ansible-home-cluster/deploy-app/deploy-code.yml --limit sugar \
  -e @"$HOME/.config/home-cluster/blakken.yml" \
  -e @"$HOME/.config/home-cluster/blakken-secrets.yml" --ask-vault-pass
```

Sugar's private configuration sets `app_collectstatic_clear: false`.
The matching Ansible role updates collected assets without deleting uploaded app
downloads under `/srv/blakken/static/ios/` and `/srv/blakken/static/android/`.
Old hashed assets are retained too; do not clear static storage without first
preserving app downloads.
