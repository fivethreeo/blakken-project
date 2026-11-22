# 17. Stay useful when a task gets interrupted

The [deployment result](16-read-the-deployment.md) can include a blocker, an
unfinished device check, or a next step. Work also pauses for ordinary reasons.

The conversation uses short messages:

> continue

and:

> stop task

Their meaning comes from what is active.

## Continue the unfinished thing

After a build or credential interruption, "continue" means resume that work
with its existing source and target. The AI should know which stage completed
and avoid repeating uploads or deployments blindly.

If the conversation resumed after a long gap, inspect the current state.
A past successful run is not automatically the latest release, and a private
setting may have changed. Use history to recover context, then verify the
current prerequisite.

## Stop the thing you started

For these docs, "stop task" stopped the docs server on port 8003 and verified
the address no longer responded. It did not delete the docs, revert their
source, or stop all unrelated processes.

If more than one relevant task is active, make the intended one clear. A short
example is:

> stop the docs server

The AI should target the process it owns, not broadly kill processes sharing
a name.

## Don't confuse interruption with recovery

A stopped preview is simple to restart. A failed migration or lost database is
not. The existing backup arrangement needs to be understood before doing a
restore.

The AI can help find backup state and propose recovery, but the target, backup,
and possible lost data must be clear before restoration. Restore into an
isolated environment first when practising. Do not overwrite the live database
as a way to learn.

A code rollback is also not automatically a schema rollback. Installed mobile
apps may still call the newer API. The person taking over needs to understand
both compatibility and data state.

## Short prompts work best when the state is visible

A useful end-of-task response tells you what changed, what passed, what became
public, what was deployed, and what remains. That makes the next short message
meaningful.

You do not need a document for every two-line exchange. But before another
person takes over, capture the actual release state and access dependencies.
Otherwise "continue" relies on memories they do not have.

Next: [Take over without losing the thread](18-take-over.md).
