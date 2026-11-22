# 5. Correct the direction

The next part of [asking for a fix](04-say-whats-wrong.md) is steering it when
the AI assumes the wrong app, platform, or look.

The toolbar exchange included:

> logout refresh looks loke one button in app

Then:

> in ios app
>
> i mean

And:

> is it same on android?

The final fix separated the iOS actions. Android already used a spacer, so it
did not need the same edit. The clarification was small, but it changed where
the work belonged.

## You can correct without restarting

You do not need to rewrite the first message as a carefully phrased complete
ticket. Add the correction in the same conversation. The AI should carry the
existing task forward and update its interpretation.

This is especially useful in visual work. You may not know the desired detail
until you see the first attempt. Say what you want changed about that attempt.
If the AI is doing too much, say so.

The documentation feedback was:

> those docs are no good, not at all like I do it

Then:

> i write much shorter prompts

Finally:

> redo from scratch

That was not a request to add more examples of elaborate prompts. It rejected
the model of working the guide had adopted. Good iteration follows the
correction, not just the literal surface of the last sentence.

## Check the answer addresses the correction

For the toolbar, "both apps built" would not answer whether Android looked the
same. The useful finding was that Android already separated the controls.
The iOS change then needed a check that each action still worked independently.

For a request to remove an old control, adding a second control while leaving
the old one is not enough. The next chapter shows an actual example of this.

## Context helps, but it is not unlimited

There is a difference between a correction and a new feature. "In iOS app,
I mean" narrows the existing toolbar fix. "Is it same on Android?" asks for
comparison. Neither means redesign both toolbars or rebuild every application.

The apprentice should notice whether the AI treats the messages that way.
If it returns with a large unrelated change, bring it back to the subject.
A suggested response is simply:

> just separate those buttons

You are not trying to write the perfect prompt on the first attempt. You are
keeping the work pointed at the thing you saw.

The same applies to "redo from scratch." It can be appropriate when the
underlying direction is wrong, as with these docs. For a mostly correct
implementation, a small correction is usually easier to judge than starting
again. Choose based on the result, not on how confident the AI sounds.

A phrase such as "same on android?" works when the active subject is clear.
In a new conversation, name the feature again:

> does the management toolbar look the same on android?

That is an example of adding the minimum context needed. It is still short.
The final handoff explains how to start a fresh conversation without assuming
it knows everything this one did.

Next: [Reuse something you just liked](06-reuse-what-worked.md).
