# 18. Take over without losing the thread

You have followed [short requests](01-how-this-work-feels.md) through code,
app updates, server deployment, and [interruptions](17-when-work-stops.md).
The handoff should let you do that work, not force you to adopt a different
formal process.

## Start a fresh conversation with a small amount of real context

In this conversation, "publish" already has an app, change, target, and known
procedure. A new conversation does not necessarily have all of that.

A short example opening is:

> working on blakken management, sugar is the server
>
> add the same swipe action to menus

Or:

> management menu delete is ready, publish both apps

These are examples, not actual recorded requests. The AI should read the
repository and the relevant previous task before guessing what "same" refers
to. If the state cannot be recovered, name the feature or give the actual
commit/run reference.

After the context is established, you can go back to "publish," "continue,"
and the small corrections that make the result right.

## What must actually be transferred

The receiving maintainer needs:

| Need | Where it belongs |
| --- | --- |
| Application code and docs | This repository |
| Deployment procedure | The sibling Ansible checkout and root README |
| Protected runtime configuration | The existing protected configuration location |
| GitHub/build access | Authorized account access, not credentials in chat |
| Server/publication access | Configured operator access to the intended target |
| Backup and restore access | Existing backup procedure and protected access |
| Current release state | Actual source, build runs, public files, deployment result |

The application configuration files under `~/.config/home-cluster/` are not
substituted by these docs. The Ansible checkout must also be available.
If either is missing, deployment is blocked until the operator provides
approved access.

Do not put password values, keys, tokens, private configuration contents, or
customer records in the handoff. Explain how authorized access is obtained.

## Make the current state easy to resume

Keep a compact note in the approved task/handoff location:

```text
Working on:
What is already finished:
Application commit / deployment commit if changed:
App builds and versions:
Public URLs and artifact verification:
Server target and deployment result:
Backup/restore procedure and latest evidence:
Still needs doing:
Who can resolve an access blocker:
```

Use actual current values. Historical build numbers quoted in a conversation
are not proof of what is installed today. If something was not checked, say
that instead of leaving a misleading blank.

This is continuity for a new person or conversation, not a required form
before every short prompt.

## Do one task together, then let the apprentice lead

For the first task, keep the original developer available but let the
apprentice write the messages. They should not need the original developer to
turn "the total is missing" into an engineering specification.

Use the app, ask for the change, and wait for a result that can be tried.
If the AI asks a meaningful question, answer it. If it is moving in the wrong
direction, correct it. Once the result is ready, request the release and read
what happened.

This exercises the real skills: recognizing the right screen, identifying the
active app, judging the change, and understanding whether it reached the phone
and server. It also exposes missing access before the original developer is
unavailable.

For a release the apprentice cannot yet authorize, preparation can still be
useful. They can identify the source, understand the workflow result, and
explain what remains blocked. Record who is needed for the actual production
action instead of hiding that dependency behind a successful local build.

Pick a small non-destructive change, such as the toolbar spacing or a missing
cart label. The apprentice describes the problem, looks at the change,
corrects it if necessary, asks for publication, and checks the installed result.

Then follow a server-backed change such as menu deletion: understand the API,
test on disposable data, prepare the release, and verify deployment without
deleting live business data. Production actions still need the operator's
authorization; onboarding itself is not permission to mutate production.

Finally, practise recovery using an isolated restore. Confirm what was backed
up, that data is usable, and how live notifications are kept out of the test
restore. If no one can demonstrate the restore, the recovery part of the
handoff remains incomplete.

## What complete means here

The apprentice can get the project running, steer a change with short messages,
understand a publication/deployment result, and resume from the current state.
They have working authorized access and know whom to contact if it fails.
They can find and use the real recovery procedure.

They do not need to memorize every command. They do need to recognize when the
AI changed the wrong app, published an old artifact, skipped the API deployment,
or has not actually tested what it claims.

This reduces dependence on one person's knowledge, but it does not create
infrastructure redundancy. A single server can still fail, and backups are
useful only if recovery works. Keep those limits separate from the apprentice's
ability to run the normal change-and-release conversation. AI assistance also
does not supply missing authorization or accountability: the receiving
maintainer still decides what should change and recognizes when a task must
stop for an operator.

If any of those responsibilities still depend on the original developer's
undocumented knowledge, keep that gap explicit. Once the apprentice can repeat
the demonstrated workflow and recovery with the transferred access, the
handoff is complete.
