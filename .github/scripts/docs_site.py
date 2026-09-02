"""Assemble the versioned documentation site published on the ``gh-pages`` branch.

The site is a directory holding one subdirectory per documentation version,
plus ``develop`` (tip of ``main``) and ``stable`` (newest release) aliases::

    <site>/
      index.html        redirect to stable/
      404.html          rewrites legacy flat paths into stable/
      switcher.json     version list consumed by the theme version switcher
      .nojekyll
    develop/  stable/  2.1/  2.0/  ...

GitHub Pages does not follow symlinks, so ``stable`` is a full copy of the
newest release build rather than a link. Patch releases replace their matching
minor-version directory.
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
from typing import NoReturn
from urllib.parse import urlsplit

BUILD_INFO_NAME = ".build-info.json"
DEVELOP_DIR = "develop"
STABLE_DIR = "stable"
_BUILD_INFO_KEYS = {"version", "package_version", "commit", "ref", "built_at"}
_LEGACY_BUILD_INFO_KEYS = _BUILD_INFO_KEYS - {"package_version"}

# Published release directories use only the major and minor components.
_VERSION_RE = re.compile(r"^\d+\.\d+$")
_RELEASE_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_TARGET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SITE_FILES = {".nojekyll", "index.html", "404.html", "switcher.json"}
_SITE_SIZE_WARNING_BYTES = 800 * 1024 * 1024
_SITE_SIZE_LIMIT_BYTES = 1024 * 1024 * 1024


def _fail(message: str) -> NoReturn:
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


def _version_sort_key(version: str) -> tuple[int, int]:
    """Build a sort key ordering versions newest-first when reversed.

    Args:
        version: A minor version string such as ``2.1``.

    Returns:
        A tuple ordering by numeric components.
    """
    match = _VERSION_RE.fullmatch(version)
    if match is None:
        return (0, 0)
    major, minor = version.split(".")
    return (int(major), int(minor))


def _release_sort_key(version: str) -> tuple[int, int, int]:
    """Return the numeric ordering key for a final release version."""
    match = _RELEASE_RE.fullmatch(version)
    if match is None:
        _fail(f"invalid final release version: {version!r}; expected X.Y.Z")
    major, minor, patch = match.groups()
    return (int(major), int(minor), int(patch))


def _minor_version(version: str) -> str:
    """Return the major.minor documentation target for a final release."""
    major, minor, _ = _release_sort_key(version)
    return f"{major}.{minor}"


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


def _write_build_info(
    directory: Path,
    version: str,
    package_version: str,
    commit: str,
    ref: str,
    source_run_id: str = "",
) -> None:
    """Record what a published directory was built from.

    Args:
        directory: Published version directory.
        version: Version label of the build.
        package_version: Exact package version used to build release docs.
        commit: Commit SHA the documentation sources came from.
        ref: Git ref the documentation sources came from.
        source_run_id: GitHub Actions run that produced development documentation.
    """
    info = {
        "version": version,
        "package_version": package_version,
        "commit": commit,
        "ref": ref,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if source_run_id:
        info["source_run_id"] = source_run_id
    (directory / BUILD_INFO_NAME).write_text(json.dumps(info, indent=2) + "\n")


def _load_build_info(directory: Path) -> dict[str, str]:
    """Load and type-check a published directory's build metadata.

    Args:
        directory: Published version directory.

    Returns:
        String-valued metadata, or an empty dict if it is missing.
    """
    info_file = directory / BUILD_INFO_NAME
    if not info_file.exists():
        return {}
    try:
        info = json.loads(info_file.read_text())
    except json.JSONDecodeError as error:
        _fail(f"invalid JSON in {info_file}: {error}")
    if not isinstance(info, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in info.items()
    ):
        _fail(f"invalid build metadata in {info_file}")
    return info


def _read_build_info(directory: Path) -> dict[str, str]:
    """Read complete build metadata for a published directory.

    Args:
        directory: Published version directory.

    Returns:
        The recorded metadata, or an empty dict if it is missing.
    """
    info = _load_build_info(directory)
    if not info:
        return {}
    missing_keys = _BUILD_INFO_KEYS - info.keys()
    if missing_keys:
        info_file = directory / BUILD_INFO_NAME
        _fail(
            f"build metadata in {info_file} is missing: {', '.join(sorted(missing_keys))}"
        )
    return info


def _upgrade_legacy_build_info(directory: Path) -> dict[str, str]:
    """Upgrade the previous four-field metadata schema in place.

    Args:
        directory: Published release directory.

    Returns:
        Complete metadata using a minor documentation version.
    """
    info = _load_build_info(directory)
    if not info:
        return {}
    missing_keys = _BUILD_INFO_KEYS - info.keys()
    if not missing_keys:
        return info
    if (
        missing_keys != {"package_version"}
        or not _LEGACY_BUILD_INFO_KEYS <= info.keys()
    ):
        info_file = directory / BUILD_INFO_NAME
        _fail(
            f"build metadata in {info_file} is missing: {', '.join(sorted(missing_keys))}"
        )

    package_version = info["version"]
    info["package_version"] = package_version
    info["version"] = _minor_version(package_version)
    (directory / BUILD_INFO_NAME).write_text(json.dumps(info, indent=2) + "\n")
    return info


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
        if entry.is_dir() and _VERSION_RE.fullmatch(entry.name)
    ]
    return sorted(versions, key=_version_sort_key, reverse=True)


def _switcher_entries(site: Path, base_url: str) -> list[dict[str, object]]:
    """Build the version switcher manifest.

    The stable release is listed once, pointing at the ``stable`` alias so that
    the switcher does not duplicate its minor-version entry.

    Args:
        site: Site root directory.
        base_url: Absolute URL the site is served from, with a trailing slash.

    Returns:
        Switcher entries, newest first.
    """
    entries: list[dict[str, object]] = []
    stable_version = _read_build_info(site / STABLE_DIR).get("version", "")

    if (site / DEVELOP_DIR).is_dir():
        entries.append(
            {
                "name": "develop (main)",
                "version": DEVELOP_DIR,
                "url": f"{base_url}{DEVELOP_DIR}/",
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


def _render_index(base_url: str, target: str) -> str:
    """Render the site landing page redirecting to a documentation target.

    Args:
        base_url: Absolute URL the site is served from, with a trailing slash.
        target: Directory to redirect to.

    Returns:
        HTML source of the landing page.
    """
    target_url = f"{base_url}{target}/"
    return f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>QDK/Chemistry documentation</title>
    <meta http-equiv="refresh" content="0; url={target}/">
    <link rel="canonical" href="{target_url}">
  </head>
  <body>
    <p>Redirecting to the <a href="{target}/">{target} documentation</a>.</p>
  </body>
</html>
"""


def _render_not_found(base_path: str, known: list[str], fallback: str) -> str:
    """Render the 404 handler that rewrites legacy flat paths into ``stable``.

    Before the site was versioned, pages were served directly from the site
    root. This keeps those links working without publishing a stub per page.

    Args:
        base_path: Path component the site is served from, e.g. ``/qdk-chemistry/``.
        known: Top-level directory names that must not be rewritten.
        fallback: Directory that receives legacy flat paths.

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
                    basePath + {json.dumps(fallback)} + "/" + rest +
                    window.location.search + window.location.hash
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
        <li><a href="{base_path}{DEVELOP_DIR}/">{DEVELOP_DIR}</a> &mdash; the development version</li>
      </ul>
      <p>If you followed a link to an older release, the page may have been
      renamed or removed since. Try searching from
      <a href="{base_path}{STABLE_DIR}/search.html">the current documentation</a>.</p>
    </main>
  </body>
</html>
"""


def _migrate_legacy_root(site: Path) -> None:
    """Remove the old flat Sphinx tree once stable documentation exists."""
    keep = _SITE_FILES | {DEVELOP_DIR, STABLE_DIR} | set(_discover_versions(site))
    for entry in site.iterdir():
        if entry.name in keep:
            continue
        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()


def _migrate_legacy_metadata(site: Path) -> None:
    """Upgrade stable metadata written by the previous preview workflow."""
    if not site.is_dir():
        return

    stable = site / STABLE_DIR
    if stable.is_dir():
        _upgrade_legacy_build_info(stable)


def _check_site_size(site: Path) -> None:
    """Report the assembled tree size and enforce the GitHub Pages limit."""
    size = sum(entry.stat().st_size for entry in site.rglob("*") if entry.is_file())
    size_mib = size / (1024 * 1024)
    print(f"assembled site size: {size_mib:.1f} MiB")
    if size > _SITE_SIZE_LIMIT_BYTES:
        _fail(
            f"assembled site is {size_mib:.1f} MiB; GitHub Pages allows at most "
            f"{_SITE_SIZE_LIMIT_BYTES / (1024 * 1024):.0f} MiB"
        )
    if size > _SITE_SIZE_WARNING_BYTES:
        print(
            f"warning: assembled site is {size_mib:.1f} MiB and is approaching "
            "the GitHub Pages limit",
            file=sys.stderr,
        )


def refresh(site: Path, base_url: str) -> None:
    """Regenerate the site-level index, 404 handler and switcher manifest.

    Args:
        site: Site root directory.
        base_url: Absolute URL the site is served from, with a trailing slash.
    """
    base_path = urlsplit(base_url).path or "/"
    site.mkdir(parents=True, exist_ok=True)
    _migrate_legacy_metadata(site)
    known = _discover_versions(site)
    for alias in (DEVELOP_DIR, STABLE_DIR):
        if (site / alias).is_dir():
            known.append(alias)

    (site / ".nojekyll").touch()
    if (site / STABLE_DIR).is_dir():
        _migrate_legacy_root(site)
        fallback = STABLE_DIR
        (site / "index.html").write_text(_render_index(base_url, fallback))
        (site / "404.html").write_text(_render_not_found(base_path, known, fallback))
    elif not (site / "index.html").exists() and (site / DEVELOP_DIR).is_dir():
        fallback = DEVELOP_DIR
        (site / "index.html").write_text(_render_index(base_url, fallback))
        (site / "404.html").write_text(_render_not_found(base_path, known, fallback))
    (site / "switcher.json").write_text(
        json.dumps(_switcher_entries(site, base_url), indent=2) + "\n"
    )
    print(f"site now holds: {', '.join(sorted(known)) or '(nothing)'}")
    _check_site_size(site)


def install(args: argparse.Namespace) -> None:
    """Place a freshly built HTML tree into the site.

    Args:
        args: Parsed command line arguments.
    """
    html = Path(args.html)
    if not (html / "index.html").exists():
        _fail(f"{html} does not look like a built documentation tree")

    site = Path(args.site)
    _migrate_legacy_metadata(site)
    target_name = _check_target_name(args.target)
    if target_name == DEVELOP_DIR:
        if args.version != DEVELOP_DIR:
            _fail("develop documentation must use version 'develop'")
        if args.package_version:
            _fail("develop documentation must not specify a package version")
        if args.stable:
            _fail("develop documentation cannot update stable")
        source_run_id = args.source_run_id
        previous_run_id = _read_build_info(site / target_name).get("source_run_id", "")
        if (
            source_run_id.isdigit()
            and previous_run_id.isdigit()
            and int(source_run_id) <= int(previous_run_id)
        ):
            print(
                f"kept develop/ from workflow run {previous_run_id}; "
                f"ignored older or duplicate run {source_run_id}"
            )
            refresh(site, args.base_url)
            return
    else:
        source_run_id = ""
        expected_target = _minor_version(args.package_version)
        if target_name != expected_target or args.version != expected_target:
            _fail(
                f"release {args.package_version} must publish with version and target "
                f"{expected_target!r}"
            )
        previous_version = _read_build_info(site / target_name).get(
            "package_version", ""
        )
        if previous_version and _release_sort_key(
            args.package_version
        ) < _release_sort_key(previous_version):
            _fail(
                f"refusing to replace {target_name}/ built from newer release "
                f"{previous_version} with {args.package_version}"
            )

    target = site / target_name
    _replace_tree(html, target)
    _write_build_info(
        target,
        args.version,
        args.package_version,
        args.commit,
        args.ref,
        source_run_id,
    )
    print(f"installed {args.version} ({args.commit[:8]}) into {target.name}/")

    if args.stable:
        stable = site / STABLE_DIR
        stable_package_version = _read_build_info(stable).get("package_version", "")
        if stable_package_version and _release_sort_key(
            args.package_version
        ) < _release_sort_key(stable_package_version):
            print(
                f"kept stable/ at newer release {stable_package_version}; "
                f"published maintenance release {args.package_version} only to {target.name}/"
            )
        else:
            _replace_tree(target, stable)
            print(f"updated stable/ to {args.package_version}")

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
    install_parser = parser.add_subparsers(required=True).add_parser(
        "install", help="publish a built HTML tree"
    )
    install_parser.add_argument("--html", required=True, help="built HTML directory")
    install_parser.add_argument(
        "--target", required=True, help="directory to publish into"
    )
    install_parser.add_argument(
        "--version", required=True, help="version label of the build"
    )
    install_parser.add_argument(
        "--package-version",
        default="",
        help="exact X.Y.Z package version used for release documentation",
    )
    install_parser.add_argument(
        "--commit", default="", help="commit the sources came from"
    )
    install_parser.add_argument(
        "--ref", default="", help="git ref the sources came from"
    )
    install_parser.add_argument(
        "--source-run-id",
        default="",
        help="GitHub Actions run that produced development documentation",
    )
    install_parser.add_argument(
        "--stable", action="store_true", help="update stable if this is newest"
    )
    install_parser.set_defaults(func=install)

    args = parser.parse_args()
    if not args.base_url.endswith("/"):
        args.base_url += "/"
    args.func(args)


if __name__ == "__main__":
    main()
