# 7. One menu feature, several pieces

After [dish and category actions](06-reuse-what-worked.md), the next request was:

> add delete for menus aswell both swipe and in edit view

This builds on what was already established. "As well" connects menus to the
existing deletion style. "Both" here means two entry points: the swipe action
and the edit view. The active work covered the management apps on both platforms.

## The AI has to follow the whole feature

The implementation needed more than two buttons:

| Piece | Why it matters |
| --- | --- |
| Django DELETE route | The phone must be able to delete server data |
| Restaurant authorization | One restaurant must not delete another's menu |
| Confirmation in both entry points | A gesture must not silently erase a menu |
| Refreshed native state | The editor/list must not keep using a deleted record |
| Default-menu handling | A remaining menu may need to become the default |
| Order history | Past orders must survive the menu change |

The resulting route is:

```text
DELETE /api/v1/management/restaurants/<appid>/menus/<menu_id>/
```

It is registered in `django-project/blakken/urls.py` and implemented by
`delete_management_menu` in `api.py`. The operation uses management access
checks and scopes the menu to its restaurant.

Related menu content is removed, but historical order snapshots remain. The
menu relation on an order can become null. Those are important consequences
even though the original prompt did not mention database relations.

## Read the result as a user first

The implementation response said deletion was added to both management clients,
with confirmation, and that tenant API tests passed. It also said native builds
could not be completed locally in that environment and that nothing was
published yet.

That is useful separation. Source implementation was ready; installed apps and
the live API were not automatically updated.

You can inspect the behavior on disposable data. Try cancelling each dialog,
deleting a non-default menu, and deleting the default menu. Do not use a real
restaurant's live menu as an onboarding exercise.

## What happened next

The next request was:

> do the publish dance

That built and published the two management apps. A later request:

> deploy blakken api

put the new endpoint on the live server. The later chapters explain why those
are separate steps and how to recognize whether both have finished.

For a new additive API feature, deploying the compatible server first can
avoid a temporary app/server mismatch. The AI should consider that even if a
historical release used another order.

## The whole exchange is smaller than the work

Read the three requests together:

> add delete for menus aswell both swipe and in edit view

> do the publish dance

> deploy blakken api

They do not repeat the menu ID, paths, workflows, or server settings in each
message. The feature remains the subject of the conversation. The AI should
carry that thread through implementation, artifacts, and the running API.

This is why a long checklist before every step would describe a different
workflow. The apprentice needs to understand the transitions, not recite the
technical details every time.

The implementation is already in the repository. For learning, ask the AI
to show how it works, or follow it yourself from the route to the two client
API methods. Do not send the original feature request unchanged and accidentally
start a second implementation.

You can then discuss a genuinely new change with the same short style. If
you change the consequences of deletion, such as wanting an undo, that is a
new behavioral decision rather than a small visual correction. State it
explicitly and let the AI investigate what it would require.

Next: [Customer and staff changes are different](08-customer-and-staff.md).
