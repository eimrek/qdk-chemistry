#!/usr/bin/env python3
"""Assemble the versioned documentation site published on the ``gh-pages`` branch.

The site is a directory holding one subdirectory per documentation version,
plus the ``latest`` (tip of ``main``) and ``stable`` (newest release) aliases::

    <site>/
      index.html        redirect to stable/
      404.html          rewrites legacy flat paths into stable/
      switcher.json     version list consumed by the theme version switcher
      .nojekyll
      latest/  stable/  2.1.0/  2.0.0/  ...

GitHub Pages does not follow symlinks, so ``stable`` is a full copy of the
newest release build rather than a link.

Subcommands:
    install: place a freshly built HTML tree into the site
    promote: copy an existing version directory to a new version and alias

Both subcommands regenerate the site-level index, 404 handler and switcher
manifest afterwards.
"""

# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See LICENSE.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

BUILD_INFO_NAME = ".build-info.json"
LATEST_DIR = "latest"
STABLE_DIR = "stable"

# Directory names that are valid publication targets: a version, or an alias.
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+[A-Za-z0-9.]*$")
_TARGET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _fail(message: str) -> None:
    """Print an error and exit with a non-zero status.

    Args:
        message: Description of what went wrong.
    """
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def _check_target_name(name: str) -> str:
    """Validate a directory name used as a publication target.

    Args:
        name: Candidate directory name.

    Returns:
        The validated name.
    """
    if not _TARGET_RE.match(name):
        _fail(f"invalid directory name: {name!r}")
    return name


def _version_sort_key(version: str) -> tuple[int, int, int, int, str]:
    """Build a sort key ordering versions newest-first when reversed.

    Args:
        version: A version string such as ``2.1.0`` or ``2.2.0rc1``.

    Returns:
        A tuple ordering by numeric components, with final releases ranked
        above prereleases of the same number.
    """
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)(.*)$", version)
    if match is None:
        return (0, 0, 0, 0, version)
    major, minor, patch, suffix = match.groups()
    # An empty suffix is a final release and sorts after any prerelease.
    return (int(major), int(minor), int(patch), 0 if suffix else 1, suffix)


def _replace_tree(source: Path, destination: Path) -> None:
    """Replace ``destination`` with a copy of ``source``.

    Args:
        source: Directory to copy from.
        destination: Directory to overwrite.
    """
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)


def _write_build_info(directory: Path, version: str, commit: str, ref: str) -> None:
    """Record what a published directory was built from.

    Args:
        directory: Published version directory.
        version: Version label of the build.
        commit: Commit SHA the documentation sources came from.
        ref: Git ref the documentation sources came from.
    """
    info = {
        "version": version,
        "commit": commit,
        "ref": ref,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (directory / BUILD_INFO_NAME).write_text(json.dumps(info, indent=2) + "\n")


def _read_build_info(directory: Path) -> dict[str, str]:
    """Read the build metadata of a published directory.

    Args:
        directory: Published version directory.

    Returns:
        The recorded metadata, or an empty dict if it is missing.
    """
    info_file = directory / BUILD_INFO_NAME
    if not info_file.exists():
        return {}
    return json.loads(info_file.read_text())


def _discover_versions(site: Path) -> list[str]:
    """List the archived version directories of a site, newest first.

    Args:
        site: Site root directory.

    Returns:
        Version directory names, newest first.
    """
    versions = [
        entry.name
        for entry in site.iterdir()
        if entry.is_dir() and _VERSION_RE.match(entry.name)
    ]
    return sorted(versions, key=_version_sort_key, reverse=True)


def _switcher_entries(site: Path, base_url: str) -> list[dict[str, object]]:
    """Build the version switcher manifest.

    The stable release is listed once, pointing at the ``stable`` alias so that
    the canonical URL is the one users share.

    Args:
        site: Site root directory.
        base_url: Absolute URL the site is served from, with a trailing slash.

    Returns:
        Switcher entries, newest first.
    """
    entries: list[dict[str, object]] = []
    stable_version = _read_build_info(site / STABLE_DIR).get("version", "")

    if (site / LATEST_DIR).is_dir():
        entries.append(
            {
                "name": "latest (main)",
                "version": LATEST_DIR,
                "url": f"{base_url}{LATEST_DIR}/",
            }
        )
    if stable_version:
        entries.append(
            {
                "name": f"{stable_version} (stable)",
                "version": stable_version,
                "url": f"{base_url}{STABLE_DIR}/",
                "preferred": True,
            }
        )
    for version in _discover_versions(site):
        if version == stable_version:
            continue
        entries.append({"version": version, "url": f"{base_url}{version}/"})
    return entries


def _render_index(base_url: str) -> str:
    """Render the site landing page redirecting to the stable documentation.

    Args:
        base_url: Absolute URL the site is served from, with a trailing slash.

    Returns:
        HTML source of the landing page.
    """
    stable_url = f"{base_url}{STABLE_DIR}/"
    return f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>QDK/Chemistry documentation</title>
    <meta http-equiv="refresh" content="0; url={STABLE_DIR}/">
    <link rel="canonical" href="{stable_url}">
  </head>
  <body>
    <p>Redirecting to the <a href="{STABLE_DIR}/">stable documentation</a>.</p>
  </body>
</html>
"""


def _render_not_found(base_path: str, known: list[str]) -> str:
    """Render the 404 handler that rewrites legacy flat paths into ``stable``.

    Before the site was versioned, pages were served directly from the site
    root. This keeps those links working without publishing a stub per page.

    Args:
        base_path: Path component the site is served from, e.g. ``/qdk-chemistry/``.
        known: Top-level directory names that must not be rewritten.

    Returns:
        HTML source of the 404 page.
    """
    return f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Page not found &#8212; QDK/Chemistry</title>
    <style>
      :root {{
        color-scheme: light dark;
        --fg: #222832;
        --muted: #48566b;
        --bg: #ffffff;
        --surface: #f3f4f5;
        --border: #d1d5da;
        --link: #0a7d91;
      }}
      @media (prefers-color-scheme: dark) {{
        :root {{
          --fg: #ced6dd;
          --muted: #9ca4af;
          --bg: #14181e;
          --surface: #222832;
          --border: #48566b;
          --link: #3fb1c5;
        }}
      }}
      body {{
        margin: 0;
        min-height: 100vh;
        display: flex;
        align-items: center;
        justify-content: center;
        background: var(--bg);
        color: var(--fg);
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
        line-height: 1.6;
      }}
      main {{
        max-width: 34rem;
        padding: 2.5rem;
        margin: 1rem;
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 0.5rem;
      }}
      h1 {{ margin: 0 0 0.25rem; font-size: 1.5rem; }}
      p {{ color: var(--muted); }}
      code {{
        background: var(--bg);
        border: 1px solid var(--border);
        border-radius: 0.25rem;
        padding: 0.1rem 0.3rem;
        font-size: 0.9em;
      }}
      ul {{ padding-left: 1.1rem; }}
      a {{ color: var(--link); }}
    </style>
    <script>
      (function () {{
        var basePath = {json.dumps(base_path)};
        var known = {json.dumps(known)};
        var path = window.location.pathname;
        if (path.indexOf(basePath) !== 0) {{
          return;
        }}
        var rest = path.slice(basePath.length);
        var first = rest.split("/")[0];
        // Anything already inside a version directory is genuinely missing.
        if (rest === "" || known.indexOf(first) !== -1) {{
          return;
        }}
        window.location.replace(
          basePath + {json.dumps(STABLE_DIR)} + "/" + rest + window.location.hash
        );
      }})();
    </script>
  </head>
  <body>
    <main>
      <h1>Page not found</h1>
      <p>This page does not exist in the version of the documentation you requested.</p>
      <p>The documentation is published per version:</p>
      <ul>
        <li><a href="{base_path}{STABLE_DIR}/">{STABLE_DIR}</a> &mdash; the latest release</li>
        <li><a href="{base_path}{LATEST_DIR}/">{LATEST_DIR}</a> &mdash; the development version</li>
      </ul>
      <p>If you followed a link to an older release, the page may have been
      renamed or removed since. Try searching from
      <a href="{base_path}{STABLE_DIR}/search.html">the current documentation</a>.</p>
    </main>
  </body>
</html>
"""


def refresh(site: Path, base_url: str) -> None:
    """Regenerate the site-level index, 404 handler and switcher manifest.

    Args:
        site: Site root directory.
        base_url: Absolute URL the site is served from, with a trailing slash.
    """
    base_path = urlsplit(base_url).path or "/"
    known = _discover_versions(site)
    for alias in (LATEST_DIR, STABLE_DIR):
        if (site / alias).is_dir():
            known.append(alias)

    (site / ".nojekyll").touch()
    (site / "index.html").write_text(_render_index(base_url))
    (site / "404.html").write_text(_render_not_found(base_path, known))
    (site / "switcher.json").write_text(
        json.dumps(_switcher_entries(site, base_url), indent=2) + "\n"
    )
    print(f"site now holds: {', '.join(sorted(known)) or '(nothing)'}")


def install(args: argparse.Namespace) -> None:
    """Place a freshly built HTML tree into the site.

    Args:
        args: Parsed command line arguments.
    """
    html = Path(args.html)
    if not (html / "index.html").exists():
        _fail(f"{html} does not look like a built documentation tree")

    site = Path(args.site)
    target = site / _check_target_name(args.target)
    _replace_tree(html, target)
    _write_build_info(target, args.version, args.commit, args.ref)
    print(f"installed {args.version} ({args.commit[:8]}) into {target.name}/")

    if args.alias:
        alias = site / _check_target_name(args.alias)
        _replace_tree(target, alias)
        print(f"aliased {target.name}/ as {alias.name}/")

    refresh(site, args.base_url)


def promote(args: argparse.Namespace) -> None:
    """Copy an already published directory to a version directory and alias.

    This is the release path: the documentation for the tagged commit has
    normally already been built and published as ``latest``, so promoting it
    avoids rebuilding. The recorded commit must match the release, otherwise
    ``latest`` has drifted ahead of the tag and the caller must rebuild.

    Args:
        args: Parsed command line arguments.
    """
    site = Path(args.site)
    source = site / _check_target_name(args.source)
    if not source.is_dir():
        _fail(f"{source} does not exist; nothing to promote")

    info = _read_build_info(source)
    if args.expect_commit and info.get("commit") != args.expect_commit:
        _fail(
            f"{args.source} was built from {info.get('commit', 'an unknown commit')!r}, "
            f"expected {args.expect_commit!r}; rebuild instead of promoting"
        )

    target = site / _check_target_name(args.target)
    _replace_tree(source, target)
    _write_build_info(target, args.version, info.get("commit", ""), args.ref)
    print(f"promoted {source.name}/ to {target.name}/")

    if args.alias:
        alias = site / _check_target_name(args.alias)
        _replace_tree(target, alias)
        print(f"aliased {target.name}/ as {alias.name}/")

    refresh(site, args.base_url)


def main() -> None:
    """Parse arguments and dispatch to the requested subcommand."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", required=True, help="site root directory")
    parser.add_argument(
        "--base-url",
        required=True,
        help="absolute URL the site is served from (trailing slash)",
    )
    subparsers = parser.add_subparsers(required=True)

    install_parser = subparsers.add_parser("install", help="publish a built HTML tree")
    install_parser.add_argument("--html", required=True, help="built HTML directory")
    install_parser.add_argument(
        "--target", required=True, help="directory to publish into"
    )
    install_parser.add_argument(
        "--version", required=True, help="version label of the build"
    )
    install_parser.add_argument(
        "--commit", default="", help="commit the sources came from"
    )
    install_parser.add_argument(
        "--ref", default="", help="git ref the sources came from"
    )
    install_parser.add_argument(
        "--alias", default="", help="additional directory to copy into"
    )
    install_parser.set_defaults(func=install)

    promote_parser = subparsers.add_parser("promote", help="copy an existing directory")
    promote_parser.add_argument(
        "--source", default=LATEST_DIR, help="directory to promote"
    )
    promote_parser.add_argument(
        "--target", required=True, help="directory to publish into"
    )
    promote_parser.add_argument(
        "--version", required=True, help="version label of the release"
    )
    promote_parser.add_argument("--ref", default="", help="git ref of the release")
    promote_parser.add_argument(
        "--alias", default="", help="additional directory to copy into"
    )
    promote_parser.add_argument(
        "--expect-commit",
        default="",
        help="require the source to have been built from this commit",
    )
    promote_parser.set_defaults(func=promote)

    args = parser.parse_args()
    if not args.base_url.endswith("/"):
        args.base_url += "/"
    args.func(args)


if __name__ == "__main__":
    main()
