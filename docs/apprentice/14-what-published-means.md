# 14. Check the phone-facing result

The [publish dance](13-the-publish-dance.md) finishes at the public download,
not at "upload succeeded."

The useful response to the toolbar publication named the commit, said both
Management builds passed, and gave the public APK, versioned IPA, and SideStore
source. It also said Maharaja's listing was preserved.

That is what connects the short request to an actual installable result.

## The established URLs

| What you need | URL |
| --- | --- |
| Management Android | `https://blakken.cavabonga.no/static/android/BlakkenManagement.apk` |
| Maharaja Android | `https://blakken.cavabonga.no/static/android/Maharaja.apk` |
| SideStore source | `https://blakken.cavabonga.no/static/source/source.json` |
| Management direct IPA | `https://blakken.cavabonga.no/static/ios/BlakkenManagement.ipa` |
| Maharaja direct IPA | `https://blakken.cavabonga.no/static/ios/Maharaja.ipa` |

SideStore updates normally point at versioned releases under
`/static/source/releases/`. Updating the source listing does not prove a
separate direct IPA URL was updated too. Read the actual published URL in the
response instead of inventing a versioned filename.

## What the AI verifies

It should fetch the public binary and compare it with the selected workflow
artifact. Matching size and SHA-256 show the bytes agree. HTTP 200 alone does
not tell you whether the file contains the new change.

For SideStore, it should check the app's version/build and the linked IPA, while
preserving the other app's entry. For Android, it should check that the published
APK is the correct app and intended build.

This is machine work the AI can do. Your short "publish" request does not need
to spell out a hashing algorithm each time.

## What you still do on the device

SideStore users refresh the source and confirm installation. Publishing the
source is not a silent update to every installed phone.

On Android, downloading an APK is not the same as having installed it. A
signature mismatch can also prevent an update. Do not casually uninstall and
discard app data to bypass that without understanding the consequence.

Once the new app is installed, look for the change you asked for. A cart-total
fix should now be visible in the cart. The menu delete affordance should be
present in the staff screen.

## If you are still seeing the old result

Short example:

> still looks the same

The AI should first distinguish an old installation, stale public download,
wrong app/platform, and a real failed fix. Rewriting the feature immediately
can hide a publication problem.

Next: [Deploying the API is another step](15-deploy-the-api.md).
