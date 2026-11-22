# 13. The publish dance

After [the source is ready](12-before-you-say-publish.md), the request may be:

> do the publish dance

This is shorthand for the established native release work, not a special
command you type into a shell.

For menu deletion, the dance published Management iOS and Android. Maharaja's
SideStore entry remained in place.

## What happens behind the short request

The AI gets the intended source onto the release path, runs the affected native
workflows, waits for their results, downloads the artifacts, publishes the
correct public files, and checks what users can fetch.

The workflows are:

| Workflow | What it produces |
| --- | --- |
| Build Management iOS | Unsigned Management IPA |
| Build Management Android | Management debug APK |
| Build Maharaja iOS | Unsigned Maharaja IPA |
| Build Maharaja Android | Maharaja debug APK |

They live under `.github/workflows/`. iOS builds use macOS/Xcode; Android builds
use the configured Java, SDK, and Gradle environment.

The builds need the target API and WebSocket URLs. Maharaja also needs its
restaurant app ID. In an established release conversation those may already
be known. In a new environment they must be confirmed, not guessed.

## Two publication paths

Android publication updates the appropriate public APK. The workflows produce
artifacts; they do not themselves publish those APKs to the public server.

iOS uses `scripts/publish_sidestore_source.py` for SideStore. It downloads the
selected successful workflow artifact, validates bundle/configuration, and
publishes versioned files and the source listing.

For a Management-only update, the helper invocation is:

```sh
python3 scripts/publish_sidestore_source.py --management-run <run-id>
```

For Maharaja, use `--maharaja-run`. `--dry-run` prepares files without uploading.
The first publication needs both apps; later updates can preserve the app
that did not change.

The AI should select the actual run ID and use configured operator access.
These example commands are explanation, not a reason to publish something
while reading the guide.

## Failed builds are still unfinished work

An earlier Maharaja iOS build exposed Swift continuation type errors, while
an Android workflow needed an SDK setup correction. Those failures were fixed
and only the necessary builds rerun.

That is part of doing the task, not a reason to call an unbuilt release
complete. The AI's final publication response should show successful builds,
the app/version, and full public locations.

## You don't need to supervise every build step

The useful division of work is that you request the release and judge the
outcome, while the AI handles the build procedure and follows failures through.
You should not have to keep asking it to check whether the command it started
finished successfully.

If the response says only "workflow started," the release is still underway.
If it says "published" but gives no app or location, ask the missing question.
If it says iOS passed and Android failed, it has not completed a two-platform
publication.

The source helper is specifically for iOS. It does not make the Android APK
public, and a GitHub artifact is not the public Android download either.
Those distinctions belong in the AI's execution even when the request is
just "publish."

The report need not overwhelm you with every log line. It should make the
meaningful result clear: which change, which app, successful builds, and where
to install it. The underlying run IDs and hashes should be recoverable when
you or the next maintainer needs to inspect them.

Next: [Check the phone-facing result](14-what-published-means.md).
