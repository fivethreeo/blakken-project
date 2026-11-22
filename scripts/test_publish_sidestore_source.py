import json
from pathlib import Path
import tempfile
import unittest
import zipfile
import plistlib

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
