# 10. When access gets in the way

[Live behavior](09-live-not-manual.md), ordering, and management editing all
depend on the right access. A short symptom such as "can't log in" is fine,
but the fix may be different from a screen repair.

The AI needs to distinguish credentials, restaurant membership, token expiry,
and app verification. Changing one does not solve all four.

## The apps and server make separate decisions

Management users still need valid credentials and restaurant membership.
Knowing the public restaurant ID is not permission to manage it.

Official app verification is another layer. The project supports Apple App
Attest and Google Play Integrity. The current SideStore/debug workflows turn
client verification off, but the server's corresponding policy must independently
allow those clients.

Customer ordering policy belongs to the restaurant. Management login/refresh
policy belongs to the deployment. An app configuration ID is not the same as
the restaurant app ID.

You do not need to include all of this in every prompt. The AI should inspect
the current configuration and explain the relevant distinction when a failure
depends on it.

## The status-page request

One actual request was:

> add thst status page

The conversation had already established the verification problem. The result
was an admin page that shows policy, missing setup, and provider checks:

```text
/admin/blakken/nativeappregistration/verification-status/
```

It is permission-protected. Loading it performs local checks; checking Google
credentials is an explicit action. A successful credential check is not proof
that a store build or real phone passes verification.

## What not to infer

An unsigned SideStore IPA is not an officially signed App Attest release.
A debug APK is not a Play-recognized store release. A successful GitHub workflow
does not change that.

The project has integration support, but official signing, provider setup, and
real-device validation still need their own work. The root README gives the
detailed settings when you need them.

## Keep the conversation useful and safe

Tell the AI the platform and sanitized error if they are missing. Do not paste
passwords, token values, service-account credentials, or customer data into
the conversation.

If a policy change is genuinely intended, make that intent clear. It is not
something the AI should quietly do to make a login test succeed.

The short example "check why management login fails" is enough to request
investigation in context. It is not permission to disable verification,
replace credentials, or grant additional memberships.

Next: [Let the AI do the checking](11-read-the-checks.md).
