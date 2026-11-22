# 4. Say what is wrong

[Having the app open](03-get-it-running.md) lets you start from observation.
You do not need to diagnose the source file before asking for a fix.

The actual cart request was:

> cart does not show total

This says what the shopper is missing. It does not prescribe a particular
Swift view, Kotlin component, or arithmetic helper. The AI can find the
existing basket calculation and render the amount.

## Add the missing fact, not a whole new specification

If the conversation is already about Maharaja, the app is established.
If it is not, a short example would be:

> maharaja cart does not show total

If you are looking at only one platform:

> on android

The aim is to resolve ambiguity, not pad the prompt. A screenshot can do more
than a long description when the issue is visual.

The same pattern applies to a failure. "Can't log in" identifies the symptom,
but the AI may need the platform and sanitized error. Give those as they
become relevant. Do not provide a password or access token as debugging context.

## What a useful result looks like

For the cart, you want a visible total that changes with prices and quantities.
You should be able to add an item, change a quantity, remove an item, and see
the amount follow the basket.

You do not have to list every check in the original prompt. The AI should
recognize the dependent behavior. But after the change, look at the screen
yourself when possible. A compilation report does not show whether the amount
is visible or whether it wraps badly.

If the result is wrong, say what is still wrong:

> total disappears when i remove an item

That is a suggested follow-up, not something that happened in the recorded
cart task. It is the same style: keep the next message about the actual result.

## Don't confuse a fix with publication

After the cart request, the separate message was:

> publish after

That added release work. The final response reported both customer builds
succeeded and gave the public APK and SideStore update.

Without publication, source changed in the checkout is not an update on a
customer's phone. Keep that distinction in mind even when the whole exchange
takes only two messages.

Next: [Correct the direction](05-correct-the-direction.md).
