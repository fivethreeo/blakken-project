# 1. How this work feels

This is a guide to taking over work on Blakken in the way it has actually been
done here: look at the application, tell the AI what you want, see what it
changes, correct it, and release when ready.

You do not start by writing a specification for every small change.

The cart conversation was:

> cart does not show total

Then:

> publish after

That was enough to start a concrete fix. The AI inspected the customer apps,
added the live total, built the changed apps, and published them. The useful
part of the prompt was the problem. The quantity/price calculation, source
files, and build commands were work for the AI to find.

## Your part is still important

You notice that something is missing or feels wrong. You choose the behavior
you want. You look at the result and say when it is not right.

That last part matters. These docs themselves went through it: the first
versions described a formal process with long prompts. The correction was
simply that the prompts used in practice are much shorter. More pages did not
fix that mismatch. This version starts with the conversation instead.

The apprentice is not being trained to memorize commands or produce elaborate
instructions. You are learning enough about the project to know what you are
looking at, steer the work, and recognize whether the reported result answers
the actual request.

## What the AI does

The AI should inspect the repository, make the change, keep related code
consistent, and run the appropriate checks. When a release is requested, it
should use the established build and publication procedure.

A short prompt does not make an untested result acceptable. You can say
"publish" without spelling out every build command; the response should still
tell you what was built and where it was published. If there is a missing
credential, unclear target, or failed check, it should say so rather than
pretending the release finished.

## How to read this guide

The chapters follow the same rhythm as the work. First recognize the parts,
then make and correct changes. Later chapters unpack what "publish" and
"deploy blakken api" actually involve. The last chapter puts everything the
next maintainer needs in one place.

Real messages are quoted as real messages. Suggested prompts are labeled as
examples. You do not need to copy them word for word or reproduce the user's
spelling. Keep the request natural.

Next: [Know what you are looking at](02-know-the-project.md).
