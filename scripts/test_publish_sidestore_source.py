import json
from pathlib import Path
import tempfile
import unittest
import zipfile
import plistlib
from unittest.mock import patch

import publish_sidestore_source
from publish_sidestore_source import APPS, make_source, read_ipa, save_local_files


class SideStoreSourceTests(unittest.TestCase):
    def make_ipa(self, path, config, *, version="1.0", build_version="10", api_base_url="https://blakken.cavabonga.no/"):
        info = {
            "CFBundleIdentifier": config["bundle_id"],
            "CFBundleShortVersionString": version,
            "CFBundleVersion": build_version,
            "API_BASE_URL": api_base_url,
            "TS_WS_BACKEND_URL": "wss://blakken.cavabonga.no/ws/",
            "APP_ATTEST_REQUIRED": False,
            "APP_REGISTRATION_ID": "",
        }
        if config.get("app_id"):
            info["RESTAURANT_APP_ID"] = config["app_id"]
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(
                f"Payload/{config['name']}.app/Info.plist",
                plistlib.dumps(info),
            )
        return path

    def test_reads_matching_production_ipa_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            config = APPS[0]
            ipa = self.make_ipa(Path(directory) / "Maharaja.ipa", config)
            release = read_ipa(ipa, config)
        self.assertEqual(release.version, "1.0")
        self.assertEqual(release.build_version, "10")

    def test_download_uses_fresh_temp_directory_when_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            config = APPS[0]
            old_artifact = output / "artifacts/maharaja/Maharaja.ipa"
            old_artifact.parent.mkdir(parents=True)
            self.make_ipa(old_artifact, config, build_version="10")

            def download(args):
                temp_dir = Path(args[args.index("--dir") + 1])
                self.make_ipa(temp_dir / config["ipa"], config, build_version="11")

            with patch.object(publish_sidestore_source, "command", side_effect=download):
                release = publish_sidestore_source.download_release("123", config, output)

            self.assertEqual(release.build_version, "11")

    def test_rejects_non_production_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            config = APPS[0]
            ipa = self.make_ipa(
                Path(directory) / "Maharaja.ipa", config, api_base_url="http://localhost/",
            )
            with self.assertRaisesRegex(RuntimeError, "production API"):
                read_ipa(ipa, config)

    def test_source_prepends_current_build_and_preserves_history(self):
        releases = []
        with tempfile.TemporaryDirectory() as directory:
            for config in APPS:
                ipa = self.make_ipa(
                    Path(directory) / config["ipa"], config,
                    build_version="22.3",
                )
                releases.append(read_ipa(ipa, config))
            previous = {
                "apps": [{
                    "bundleIdentifier": APPS[0]["bundle_id"],
                    "versions": [
                        {"version": "1.0", "buildVersion": "22.2", "downloadURL": "https://example/old.ipa"},
                    ],
                }],
            }
            source = make_source(releases, previous)
        self.assertEqual(len(source["apps"]), 2)
        maharaja = source["apps"][0]
        self.assertEqual(maharaja["versions"][0]["buildVersion"], "22.3")
        self.assertEqual(maharaja["versions"][1]["downloadURL"], "https://example/old.ipa")
        self.assertEqual(maharaja["appPermissions"], {"entitlements": [], "privacy": {}})

    def test_source_keeps_unchanged_app_when_only_one_app_is_released(self):
        config = APPS[0]
        with tempfile.TemporaryDirectory() as directory:
            ipa = self.make_ipa(Path(directory) / config["ipa"], config, build_version="22.3")
            release = read_ipa(ipa, config)
            management = {
                "name": "Blakken Management",
                "bundleIdentifier": APPS[1]["bundle_id"],
                "versions": [{
                    "version": "1.0",
                    "buildVersion": "16.1",
                    "downloadURL": "https://example/management.ipa",
                }],
            }
            source = make_source([release], {"apps": [management]})
        self.assertEqual(
            [app["bundleIdentifier"] for app in source["apps"]],
            [APPS[0]["bundle_id"], APPS[1]["bundle_id"]],
        )
        self.assertEqual(source["apps"][1]["versions"], management["versions"])

    def test_saves_ipa_icons_and_parseable_source(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            releases = []
            for config in APPS:
                ipa = self.make_ipa(Path(directory) / config["ipa"], config)
                releases.append(read_ipa(ipa, config))
            source = make_source(releases, {"apps": []})
            files = save_local_files(output, releases, source)
            self.assertEqual(len(files), 5)
            self.assertEqual(json.loads((output / "source.json").read_text())["name"], "Blakken Apps")
            self.assertTrue((output / "icons/maharaja.png").is_file())
            self.assertTrue((output / "icons/management.png").is_file())


if __name__ == "__main__":
    unittest.main()
