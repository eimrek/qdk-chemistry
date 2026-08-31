# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See LICENSE.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Tests for versioned documentation site assembly."""

import argparse
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "docs_site.py"
SPEC = importlib.util.spec_from_file_location("docs_site", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise ImportError(f"Unable to load {SCRIPT}")
docs_site = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(docs_site)


class DocsSiteTest(unittest.TestCase):
    """Exercise publication and migration behavior."""

    def setUp(self) -> None:
        """Create an isolated site root for each test."""
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.site = self.root / "site"
        self.site.mkdir()

    def tearDown(self) -> None:
        """Remove the isolated site root."""
        self.temporary_directory.cleanup()

    def _html(self, marker: str) -> Path:
        """Create a minimal documentation build containing a marker."""
        html = self.root / f"html-{marker}"
        html.mkdir()
        (html / "index.html").write_text(marker)
        return html

    def _install(
        self,
        target: str,
        version: str,
        package_version: str = "",
        *,
        stable: bool = False,
    ) -> None:
        """Install a minimal documentation build into the test site."""
        marker = package_version or version
        docs_site.install(
            argparse.Namespace(
                html=str(self._html(marker)),
                site=str(self.site),
                target=target,
                version=version,
                package_version=package_version,
                commit="abcdef123456",
                ref="main" if target == "develop" else f"v{package_version}",
                stable=stable,
                base_url="https://example.test/docs/",
            )
        )

    def _package_version(self, directory: str) -> str:
        """Read the exact package version recorded for a directory."""
        info = json.loads(
            (self.site / directory / docs_site.BUILD_INFO_NAME).read_text()
        )
        return info["package_version"]

    def _legacy_release(self, directory: str, version: str) -> None:
        """Create a release directory using the previous metadata schema."""
        release = self.site / directory
        release.mkdir()
        (release / "index.html").write_text(version)
        (release / docs_site.BUILD_INFO_NAME).write_text(
            json.dumps(
                {
                    "version": version,
                    "commit": "abcdef123456",
                    "ref": f"v{version}",
                    "built_at": "2026-08-14T08:50:54+00:00",
                }
            )
        )

    def test_develop_preserves_flat_site_until_first_release(self) -> None:
        """Keep legacy root pages until stable documentation exists."""
        (self.site / "index.html").write_text("legacy")
        (self.site / "glossary.html").write_text("legacy")
        (self.site / "_static").mkdir()

        self._install("develop", "develop")

        self.assertEqual((self.site / "index.html").read_text(), "legacy")
        self.assertTrue((self.site / "glossary.html").exists())

        self._install("2.1", "2.1", "2.1.0", stable=True)

        self.assertFalse((self.site / "glossary.html").exists())
        self.assertFalse((self.site / "_static").exists())
        self.assertIn("url=stable/", (self.site / "index.html").read_text())

    def test_patch_release_replaces_minor_version_and_stable(self) -> None:
        """Replace a minor directory and stable with a newer patch."""
        self._install("2.1", "2.1", "2.1.0", stable=True)
        self._install("2.1", "2.1", "2.1.1", stable=True)

        self.assertEqual(self._package_version("2.1"), "2.1.1")
        self.assertEqual(self._package_version("stable"), "2.1.1")

    def test_older_maintenance_release_does_not_downgrade_stable(self) -> None:
        """Keep stable on the newest release across maintenance lines."""
        self._install("2.1", "2.1", "2.1.1", stable=True)
        self._install("1.1", "1.1", "1.1.1", stable=True)

        self.assertEqual(self._package_version("1.1"), "1.1.1")
        self.assertEqual(self._package_version("stable"), "2.1.1")

    def test_older_patch_cannot_replace_newer_minor_docs(self) -> None:
        """Reject replacing a minor directory with an older patch."""
        self._install("2.1", "2.1", "2.1.1", stable=True)

        with self.assertRaises(SystemExit):
            self._install("2.1", "2.1", "2.1.0", stable=True)

    def test_switcher_lists_develop_and_minor_versions(self) -> None:
        """List develop, stable, and archived minors in expected order."""
        self._install("develop", "develop")
        self._install("1.1", "1.1", "1.1.0")
        self._install("2.1", "2.1", "2.1.0", stable=True)

        entries = json.loads((self.site / "switcher.json").read_text())

        self.assertEqual(
            [entry["version"] for entry in entries], ["develop", "2.1", "1.1"]
        )

    def test_legacy_redirect_preserves_query_and_fragment(self) -> None:
        """Keep query strings and fragments when rewriting legacy URLs."""
        self._install("2.1", "2.1", "2.1.0", stable=True)

        not_found = (self.site / "404.html").read_text()

        self.assertIn("window.location.search + window.location.hash", not_found)

    def test_incomplete_build_metadata_is_rejected(self) -> None:
        """Reject metadata files without all required provenance fields."""
        directory = self.site / "2.1"
        directory.mkdir()
        (directory / docs_site.BUILD_INFO_NAME).write_text('{"version": "2.1"}')

        with self.assertRaises(SystemExit):
            docs_site._read_build_info(directory)

    def test_develop_cannot_update_stable(self) -> None:
        """Reject requests to install development docs as stable."""
        with self.assertRaises(SystemExit):
            self._install("develop", "develop", stable=True)

    def test_legacy_preview_is_removed_without_promoting_stale_html(self) -> None:
        """Remove old patch trees while retaining normalized stable docs."""
        self._legacy_release("1.1.0", "1.1.0")
        self._legacy_release("2.1.0", "2.1.0")
        self._legacy_release("stable", "2.1.0")
        self._legacy_release("latest", "latest")

        self._install("develop", "develop")

        self.assertEqual(self._package_version("stable"), "2.1.0")
        self.assertFalse((self.site / "1.1").exists())
        self.assertFalse((self.site / "2.1").exists())
        self.assertFalse((self.site / "1.1.0").exists())
        self.assertFalse((self.site / "2.1.0").exists())
        self.assertFalse((self.site / "latest").exists())


if __name__ == "__main__":
    unittest.main()
