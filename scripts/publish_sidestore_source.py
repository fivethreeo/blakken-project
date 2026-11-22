#!/usr/bin/env python3
import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_BASE_URL = "https://blakken.cavabonga.no"
SOURCE_URL = f"{PUBLIC_BASE_URL}/static/source/source.json"
STATIC_ROOT = "/srv/blakken/static/source"
APPS = (
    {
        "key": "maharaja",
        "name": "Maharaja",
        "bundle_id": "no.blakken.restaurants.maharaja",
        "workflow": "Build Maharaja iOS",
        "artifact": "maharaja-ios-sidestore-ipa",
        "ipa": "Maharaja.ipa",
        "app_id": "ca7a0000-0000-4000-8000-000000000001",
        "icon": Path("restaurant-apps/maharaja/ios/Resources/Assets.xcassets/AppIcon.appiconset/AppIcon.png"),
        "tint": "#8B1E2D",
        "description": "Order from Maharaja and follow your order status.",
    },
    {
        "key": "management",
        "name": "Blakken Management",
        "bundle_id": "no.blakken.management",
        "workflow": "Build Management iOS",
        "artifact": "management-ios-sidestore-ipa",
        "ipa": "BlakkenManagement.ipa",
        "icon": Path("management-apps/ios/Resources/Assets.xcassets/AppIcon.appiconset/AppIcon.png"),
        "tint": "#222222",
        "description": "Manage restaurant menus, opening status, and orders.",
    },
)
BUILD_VERSION_PATTERN = re.compile(r"[0-9]+(?:\.[0-9]+){0,2}\Z")
SAFE_VERSION_PATTERN = re.compile(r"[A-Za-z0-9._-]+\Z")


@dataclass(frozen=True)
class Release:
    config: dict
    ipa: Path
    version: str
    build_version: str
    size: int
    entitlements: list[str]
    privacy: dict[str, str]

    @property
    def filename(self):
        return f"{self.config['name'].replace(' ', '')}-{self.version}-{self.build_version}.ipa"


def command(args, *, capture_output=False):
    try:
        return subprocess.run(
            args, cwd=ROOT, check=True, text=True,
            capture_output=capture_output,
        )
    except subprocess.CalledProcessError as error:
        details = error.stderr.strip() if error.stderr else ""
        raise RuntimeError(f"{args[0]} failed" + (f": {details}" if details else "")) from error


def read_run(run_id, expected_workflow):
    result = command([
        "gh", "run", "view", run_id,
        "--json", "workflowName,status,conclusion,headBranch,headSha",
    ], capture_output=True)
    try:
        run = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Could not read GitHub Actions run {run_id}.") from error
    if run.get("workflowName") != expected_workflow:
        raise RuntimeError(f"Run {run_id} is not {expected_workflow}.")
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        raise RuntimeError(f"Run {run_id} has not completed successfully.")
    if run.get("headBranch") != "main":
        raise RuntimeError(f"Run {run_id} was not built from main.")
    return run


def read_ipa(ipa, config):
    try:
        with zipfile.ZipFile(ipa) as archive:
            info_paths = [
                name for name in archive.namelist()
                if name.startswith("Payload/") and name.endswith(".app/Info.plist")
            ]
            if len(info_paths) != 1:
                raise RuntimeError(f"{ipa.name} must contain exactly one iOS app.")
            app_prefix = info_paths[0].removesuffix("Info.plist")
            info = plistlib.loads(archive.read(info_paths[0]))
            entitlements_path = app_prefix + "archived-expanded-entitlements.xcent"
            entitlements = {}
            if entitlements_path in archive.namelist():
                entitlements = plistlib.loads(archive.read(entitlements_path))
    except (OSError, zipfile.BadZipFile, plistlib.InvalidFileException, KeyError) as error:
        raise RuntimeError(f"Could not read {ipa.name} as an iOS app.") from error

    if info.get("CFBundleIdentifier") != config["bundle_id"]:
        raise RuntimeError(f"{ipa.name} has an unexpected bundle identifier.")
    if info.get("API_BASE_URL") != f"{PUBLIC_BASE_URL}/":
        raise RuntimeError(f"{ipa.name} is not configured for the production API.")
    if info.get("TS_WS_BACKEND_URL") != "wss://blakken.cavabonga.no/ws/":
        raise RuntimeError(f"{ipa.name} is not configured for the production WebSocket.")
    if info.get("APP_ATTEST_REQUIRED") is not False or info.get("APP_REGISTRATION_ID", ""):
        raise RuntimeError(f"{ipa.name} must be configured for SideStore distribution.")
    if config.get("app_id") and info.get("RESTAURANT_APP_ID") != config["app_id"]:
        raise RuntimeError(f"{ipa.name} is configured for a different restaurant.")

    version = info.get("CFBundleShortVersionString")
    build_version = info.get("CFBundleVersion")
    if not isinstance(version, str) or not SAFE_VERSION_PATTERN.fullmatch(version):
        raise RuntimeError(f"{ipa.name} has an invalid marketing version.")
    if not isinstance(build_version, str) or not BUILD_VERSION_PATTERN.fullmatch(build_version):
        raise RuntimeError(f"{ipa.name} has an invalid build number.")
    privacy = {
        key: value for key, value in info.items()
        if key.endswith("UsageDescription") and isinstance(value, str)
    }
    return Release(
        config=config, ipa=ipa, version=version,
        build_version=build_version, size=ipa.stat().st_size,
        entitlements=sorted(entitlements), privacy=privacy,
    )


def download_release(run_id, config, output_dir):
    artifact_dir = output_dir / "artifacts" / config["key"]
    artifact_dir.mkdir(parents=True, exist_ok=True)
    command([
        "gh", "run", "download", run_id,
        "--name", config["artifact"],
        "--dir", str(artifact_dir),
    ])
    ipa = artifact_dir / config["ipa"]
    if not ipa.is_file():
        raise RuntimeError(f"Run {run_id} did not provide {config['ipa']}.")
    return read_ipa(ipa, config)


def fetch_previous_source():
    try:
        with urllib.request.urlopen(SOURCE_URL, timeout=15) as response:
            source = json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return {"apps": []}
        raise RuntimeError(f"Could not read the existing SideStore source ({error.code}).") from error
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError("Could not read the existing SideStore source.") from error
    if not isinstance(source, dict) or not isinstance(source.get("apps"), list):
        raise RuntimeError("The existing SideStore source has an invalid format.")
    return source


def make_source(releases, previous_source):
    previous_apps = {
        app.get("bundleIdentifier"): app
        for app in previous_source.get("apps", [])
        if isinstance(app, dict) and isinstance(app.get("bundleIdentifier"), str)
    }
    source_apps = []
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for release in releases:
        config = release.config
        filename = release.filename
        prior_app = previous_apps.get(config["bundle_id"], {})
        prior_versions = prior_app.get("versions", [])
        if not isinstance(prior_versions, list):
            raise RuntimeError(f"Existing version history for {config['name']} is invalid.")
        version_entry = {
            "version": release.version,
            "buildVersion": release.build_version,
            "date": now,
            "localizedDescription": f"Build {release.build_version}.",
            "downloadURL": f"{PUBLIC_BASE_URL}/static/source/releases/{filename}",
            "size": release.size,
        }
        versions = [version_entry]
        for old in prior_versions:
            if not isinstance(old, dict):
                continue
            same_build = (
                old.get("version") == release.version
                and str(old.get("buildVersion", "")) == release.build_version
            )
            if not same_build and isinstance(old.get("downloadURL"), str):
                versions.append(old)
            if len(versions) == 5:
                break

        icon_name = f"{config['key']}.png"
        source_apps.append({
            "name": config["name"],
            "bundleIdentifier": config["bundle_id"],
            "developerName": "Blakken",
            "subtitle": config["description"],
            "localizedDescription": config["description"],
            "iconURL": f"{PUBLIC_BASE_URL}/static/source/icons/{icon_name}",
            "tintColor": config["tint"],
            "category": "utilities",
            "versions": versions,
            "appPermissions": {
                "entitlements": release.entitlements,
                "privacy": release.privacy,
            },
        })
    return {
        "name": "Blakken Apps",
        "subtitle": "Native apps for Blakken restaurants.",
        "description": "Install and update Maharaja and Blakken Management.",
        "iconURL": f"{PUBLIC_BASE_URL}/static/source/icons/management.png",
        "website": PUBLIC_BASE_URL,
        "apps": source_apps,
        "news": [],
    }


def save_local_files(output_dir, releases, source):
    icons_dir = output_dir / "icons"
    releases_dir = output_dir / "releases"
    icons_dir.mkdir(parents=True, exist_ok=True)
    releases_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for release in releases:
        local_ipa = releases_dir / release.filename
        shutil.copy2(release.ipa, local_ipa)
        icon_name = f"{release.config['key']}.png"
        local_icon = icons_dir / icon_name
        shutil.copy2(ROOT / release.config["icon"], local_icon)
        files.extend([
            (local_ipa, f"releases/{release.filename}"),
            (local_icon, f"icons/{icon_name}"),
        ])
    local_source = output_dir / "source.json"
    local_source.write_text(json.dumps(source, indent=2) + "\n", encoding="utf-8")
    files.append((local_source, "source.json"))
    return files


def ssh_options(ssh_key):
    options = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
    if ssh_key:
        options.extend(["-i", str(ssh_key.expanduser())])
    return options


def upload(files, host, ssh_key, publication_tag):
    if not re.fullmatch(r"[A-Za-z0-9@._-]+", host):
        raise RuntimeError("SSH host must contain only letters, numbers, '.', '_', '@', or '-'.")
    options = ssh_options(ssh_key)
    result = command([
        "ssh", *options, host,
        "mktemp -d /tmp/blakken-sidestore-source.XXXXXX",
    ], capture_output=True)
    remote_stage = result.stdout.strip()
    if not re.fullmatch(r"/tmp/blakken-sidestore-source\.[A-Za-z0-9]+", remote_stage):
        raise RuntimeError("SSH returned an unexpected temporary upload directory.")
    try:
        for local_path, relative_path in files:
            if relative_path.startswith("source.json"):
                remote_name = "source.json"
            else:
                remote_name = Path(relative_path).name
            command([
                "scp", *options, str(local_path), f"{host}:{remote_stage}/{remote_name}",
            ])

        remote_root = STATIC_ROOT
        commands = [
            "set -eu",
            f"sudo install -d -o blakken -g www-data -m 0750 "
            f"{shlex.quote(remote_root)} "
            f"{shlex.quote(remote_root + '/icons')} "
            f"{shlex.quote(remote_root + '/releases')}",
        ]
        for local_path, relative_path in files:
            destination = remote_root + "/" + relative_path
            pending = destination + f".uploading-{publication_tag}"
            staged = remote_stage + "/" + Path(relative_path).name
            commands.append(
                f"sudo install -o blakken -g www-data -m 0640 "
                f"-- {shlex.quote(staged)} {shlex.quote(pending)}"
            )
            if relative_path == "source.json":
                source_pending = pending
            else:
                commands.append(
                    f"sudo mv -f -- {shlex.quote(pending)} {shlex.quote(destination)}"
                )
        commands.append(
            f"sudo mv -f -- {shlex.quote(source_pending)} "
            f"{shlex.quote(remote_root + '/source.json')}"
        )
        command(["ssh", *options, host, " && ".join(commands)])
    finally:
        command(["ssh", *options, host, f"rm -rf -- {shlex.quote(remote_stage)}"])


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Publish iOS build artifacts as a SideStore source.")
    parser.add_argument("--maharaja-run", required=True, help="Successful Build Maharaja iOS run ID")
    parser.add_argument("--management-run", required=True, help="Successful Build Management iOS run ID")
    parser.add_argument("--host", default="sugar@192.168.1.100", help="SSH destination for static files")
    parser.add_argument("--ssh-key", type=Path, help="SSH private key (otherwise use ssh-agent/default keys)")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist/sidestore")
    parser.add_argument("--dry-run", action="store_true", help="Prepare local files without uploading")
    args = parser.parse_args(argv)
    for name in ("maharaja_run", "management_run"):
        if not re.fullmatch(r"[0-9]+", getattr(args, name)):
            parser.error(f"--{name.replace('_', '-')} must be a numeric GitHub Actions run ID")
    return args


def main(argv=None):
    args = parse_args(argv)
    output_dir = args.output_dir.resolve()
    runs = [
        read_run(args.maharaja_run, APPS[0]["workflow"]),
        read_run(args.management_run, APPS[1]["workflow"]),
    ]
    if runs[0].get("headSha") != runs[1].get("headSha"):
        raise RuntimeError("Both builds must use the same commit.")

    releases = [
        download_release(run_id, config, output_dir)
        for run_id, config in zip(
            (args.maharaja_run, args.management_run), APPS, strict=True,
        )
    ]
    previous_source = fetch_previous_source()
    source = make_source(releases, previous_source)
    files = save_local_files(output_dir, releases, source)
    print(f"Prepared local SideStore assets in {output_dir}")
    if args.dry_run:
        print(f"Dry run: source JSON is {output_dir / 'source.json'}")
        return 0

    publication_tag = f"{args.maharaja_run}-{args.management_run}"
    upload(files, args.host, args.ssh_key, publication_tag)
    print(f"Published {SOURCE_URL}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
