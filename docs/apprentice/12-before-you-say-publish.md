# 12. Source ready is not release ready

[Checked code](11-read-the-checks.md) can still be sitting only in the local
checkout. The next step is giving the release an identifiable source.

You may simply say:

> publish

In the active task, that is concise permission to take the established release
path for the change. It is not a requirement to recite Git commands.

The AI should still inspect the worktree and avoid publishing someone else's
unrelated edits.

## What needs to be identified

The release needs a source commit and the right app scope. A branch name such
as `main` moves over time; the full commit SHA identifies what a build used.

For the iOS toolbar release, the report named the commit and said both
Management builds passed. For the cart-total release, it named a different
commit and the Maharaja builds.

That connection matters. An accessible APK could be yesterday's version.
Naming the change and its source lets the AI verify the right build later.

## Sometimes the checkout is complicated

During the larger native release, there were accumulated source changes.
An isolated build worktree/branch let GitHub compile the intended snapshot
without discarding the dirty main checkout. Failed customer builds were fixed
and rerun.

That was a practical response to the actual Git state, not an apprentice rule
to create a build branch for every label change.

The AI should preserve unrelated edits, stage the intended work, and report
what was committed. If application and deployment repositories both changed,
they need separate source identities.

## The current publisher has a source expectation

The SideStore helper checks successful runs from `main`. A temporary branch
build can help prove compilation, but it is not automatically eligible for the
final helper.

If builds come from different commits, the AI must explain which component
source differs and why the artifacts are still the intended release. Do not
accept "latest successful run" as the only selection criterion.

## You are deciding readiness, not packaging details

Before asking to publish, look at whether the requested behavior is now right
and whether the report contains a real blocker. If it is ready, say so naturally.

"Publish after" can also be sent while implementation is underway, as in the
cart and logout exchanges. It adds a release requirement; it does not mean
publish even if the implementation or builds fail.

For a server-backed feature, ask for the API deployment too when needed.
Publishing native binaries alone does not install the new Django route.
That separation becomes concrete in the next three chapters.

Next: [The publish dance](13-the-publish-dance.md).
