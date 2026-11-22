# 9. When the screen must change live

Some [customer changes](08-customer-and-staff.md) cannot be judged by opening
the screen once. Another user or the server changes state while the app is open.

The request was:

> ws should notify customers on shop closing live

The important words are customers, shop closing, and live. A refresh button
alone would not satisfy it.

## What the AI found

The server already published a restaurant-specific `shop.changed` hint.
The customer clients did not both listen for that public shop state. The iOS
client had private order updates, while Android did not yet have the equivalent
public shop subscription.

The fix added independent shop subscriptions to both customer apps. When the
shop closes, checkout should stop being available without throwing away the
basket. Reconnect and foreground refresh matter because phones do not stay
connected forever.

This is a good example of a short prompt leading to a multi-part investigation.
You did not need to tell the AI which message handler was missing.

## Look at the intended behavior

For a test restaurant, keep a customer app open while staff changes shop state.
The customer should learn the new state without pressing refresh. A second
customer should learn it too.

Keep another restaurant open as well. It should not receive private information
or change because the first restaurant closed.

Then disconnect and reconnect one client. The app should learn current state
even if it missed the original event. Preserve the basket through those changes.

These checks need an approved development/test restaurant. They are not a
reason to toggle the live business just to see a notification.

## Live messages don't replace server rules

A notification can tell the client to refresh availability. The server still
decides whether an order can be accepted. A phone with a stale screen must not
become permission to bypass shop state or tenant checks.

Similarly, a healthy WebSocket process is not enough. A socket can be connected
to the wrong subscription, or its event can arrive without the UI refreshing.
The AI should trace the whole path and test the failing boundary.

## Release can happen in stages

This work included a server deployment before rebuilding the apps. Then both
Maharaja and Management builds were requested and published as part of the
broader release.

Do not copy that four-build scope automatically for every future shop fix.
Release the parts that actually changed, preserving compatibility with installed
clients. The AI should explain if a wider rebuild is necessary.

Next: [When access gets in the way](10-access-is-not-a-ui-fix.md).
