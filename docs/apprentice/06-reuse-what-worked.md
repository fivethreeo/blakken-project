# 6. Reuse something you just liked

[Corrections](05-correct-the-direction.md) shape a first change. Once something
works, the next request often builds directly on it.

Maharaja gained swipe-to-remove for cart items with a hint above the list.
An old inline removal control was then removed. After that, the request for
management editing was:

> nice, i want this for remove and hide for dish and category, say swipe left for actions on top, removing requires confirmation

The prompt is longer because it contains several actual decisions, not because
every task needs a template.

## What "this" means here

The existing customer interaction was the reference: swipe left to reveal
actions, with a visible hint. The staff version needed Hide/Show and Delete
for both categories and dishes, with confirmation for removal.

The AI's job was to inspect the existing APIs and native screens. It found
visibility and deletion operations already existed. That meant the change
could reuse behavior rather than inventing a second server API.

You did not need to provide the callback names. You did need to say that
removing requires confirmation, because that is a user-facing decision.

## Similar does not mean identical

Removing a basket item and deleting a menu category have different consequences.
A basket item is a local selection; deleting a category changes restaurant
data. Carry over the interaction style, not every assumption of the first
feature.

Category visibility also affects its continuation pages. Hiding a category
must not leave another generated page of the same category visible simply
because the UI was copied from dish handling.

This is why the AI still reads the implementation even when the prompt says
"same." Similar screens can call different operations.

## What you look for

Try swiping a dish and a category. The hint should be above the relevant list.
Hide should become Show when appropriate. Delete should ask for confirmation,
and cancelling should leave the record intact.

Look for duplicate controls left over from the old UI. When the old red removal
text was no longer wanted in Maharaja, it was explicitly removed; adding swipe
did not automatically make the old text disappear.

Check both native platforms if both are part of the request. English and
Norwegian labels live in separate native resources; a good change keeps them
consistent without asking you to supply resource paths.

Next: [One menu feature, several pieces](07-menu-delete-story.md).
