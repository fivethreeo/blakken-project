# 8. Customer and staff changes are different

The [menu deletion](07-menu-delete-story.md) story is staff work. The cart-total
story is customer work. They share a server, but they do not share an installed
mobile application.

This distinction helps you understand what "publish" should update.

## Maharaja changes

Maharaja is the customer app. Recent changes included cart removal, a live cart
total, shop-closing updates, and branding in the app icon and header.

The cart-total release built Maharaja on iOS and Android. It updated Maharaja's
SideStore entry while preserving Management's entry.

The art conversation was iterative too. A reference image or a correction to
the look guided the next attempt. Once the artwork was chosen, "update,
publish" meant updating its app uses and producing new binaries, not merely
saving an SVG in the repository.

For artwork work, the AI must respect what is actually requested and permitted.
Generated or edited image work is separate from inspecting an existing asset.
You still judge whether the result looks right.

## Management changes

Management is for staff. The prompt:

> forget password on logout

followed by:

> publish after

led to a change on both platforms: clearing the password on logout or session
expiry. The publication updated Management, not Maharaja.

That change is about what remains in the client after signing out. It is not
the same as changing the server's app-verification policy. Do not let the AI
fix a client-state issue by weakening server authentication.

## Platform parity is something you check

If you notice a problem on iOS, ask whether Android has it too when that matters.
The toolbar example did exactly this. The answer can legitimately be "Android
already does this."

When both implementations need a change, the AI edits Swift/SwiftUI and
Kotlin/Compose separately. Look at the resulting behavior rather than expecting
identical source code.

Localization is shared intent, not shared files. Each app has English and
Norwegian resources on each platform. A label should not remain English only
on one platform just because the other build passed.

## Know the release scope

The app-name distinction also helps you interpret paired release reports.
The cart total changed Maharaja on iOS and Android. The password-on-logout fix
changed Management on iOS and Android. Each report preserved the other app's
SideStore entry.

"Both apps" can be ambiguous: it might mean the customer and staff roles,
or it might mean the two platforms for one role. In a conversation about the
Management release, saying "both builds" usually concerns iOS and Android.
If the AI has interpreted it differently, correct that immediately.

Similarly, a native app icon is packaged into a binary. Seeing the chosen
artwork in the source tree is not enough to see it on the phone. The new build
must contain the icon and the device must install that build. A still-old icon
can therefore be a release or installation problem rather than an artwork
problem.

When reading a publication response, check the app name. A Management fix
should not overwrite an unchanged Maharaja binary or remove its listing.
A customer cart update should not claim that the Management download now
contains the fix.

The AI should determine this from the active change. If the conversation has
switched apps, naming the app in the next short request prevents a costly
misunderstanding.

Next: [When the screen must change live](09-live-not-manual.md).
