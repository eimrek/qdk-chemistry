# Building QDK/Chemistry documentation

This documentation assumes a UNIX-like environment (Linux, macOS, or Windows Subsystem for Linux).

## Install QDK/Chemistry

The main QDK/Chemistry Python package must be installed following the instructions in [INSTALL.md](../INSTALL.md).
[Sphinx](https://www.sphinx-doc.org/en/master/), [breathe](https://breathe.readthedocs.io/en/latest/), and several related dependencies are also required.
Installing with the `all` extra covers both:

```bash
cd python
pip install '.[all]'
```

## Install other dependencies

A few other dependencies are also required:

- [Graphviz](https://graphviz.org/download/) (for rendering diagrams)
- [Doxygen](https://www.doxygen.nl/download.html) (for C++ API documentation)

Either install the package through your OS distribution (e.g., `sudo apt install graphviz doxygen` on Ubuntu) or download and install from the links above.

## Build the documentation

Once all dependencies are installed, you can build the documentation by running the following command from the `docs/` directory:

```bash
make all
```

For a clean build, you can run:

```bash
make clean all
```

This will generate the HTML documentation in the `docs/build/html/` directory.
You can open the [`index.html`](build/html/index.html) file in that directory with your web browser to view the documentation.

## Regenerating tutorial figures

The [ground-state QPE figure maintenance guide](source/_static/diagrams/README.md)
documents source ownership, regeneration commands, and screenshot-derived asset
maintenance.

## Publishing the documentation

The published site is served by GitHub Pages from the `docs/` directory of the `gh-pages` branch, and holds one directory per documentation version:

```text
docs/
  index.html      redirect to stable/
  404.html        rewrites unversioned paths into stable/
  switcher.json   version list for the theme version switcher
  dev/            tip of main
  stable/         copy of the newest release
  2.1/  ...       one directory per minor version
```

The [`Docs`](../.github/workflows/docs.yaml) workflow maintains it, and [`.github/scripts/docs_site.py`](../.github/scripts/docs_site.py) does the site assembly.

`dev/` is republished automatically after every successful `Build and Test` run on `main`. If publication fails, rerun the downstream `Docs` workflow while the artifact is available. To rebuild an expired or missing artifact, run `Build and Test` manually on `main`.

Stable releases are rebuilt from their tag against the exact package version from PyPI. A release such as `2.1.3` replaces `2.1/`; its sidebar shows `Documentation 2.1.3`, while the version switcher and URL use `2.1`. Patch-version directories are not retained. The newest version also replaces `stable/`, while an older maintenance release updates only its own minor directory. Prereleases are not published.

Python wheels are published by a separate, approval-gated pipeline. If the exact package version is not on PyPI when the GitHub release is published, the release-triggered `Docs` workflow fails with a direct error. Rerun that same workflow after the wheel is available; GitHub preserves the original release tag for the rerun.

Manual runs (`workflow_dispatch`) accept one immutable `vX.Y.Z` release tag for validating or backfilling an older stable release. The exact PyPI package version and minor-version target are derived from that tag's root [`VERSION`](../VERSION) file, and the workflow verifies that the checkout resolves to the matching tag.

All minor versions are retained. A build is currently about 50 MB and GitHub Pages limits a published site to 1 GB. The site assembler warns at 800 MB and rejects publication above 1 GB.
