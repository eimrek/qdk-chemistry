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
  404.html        rewrites legacy flat paths into stable/
  switcher.json   version list for the theme version switcher
  develop/        tip of main
  stable/         copy of the newest release
  2.1/  ...       one directory per minor version
```

The [`Docs`](../.github/workflows/docs.yaml) workflow maintains it, and [`.github/scripts/docs_site.py`](../.github/scripts/docs_site.py) does the site assembly.

`develop/` is republished automatically after every successful `Build and Test` run on `main`, reusing the documentation that workflow already builds. The artifact is uploaded only for a push to the default branch, and the privileged publishing workflow verifies the originating event and repository before downloading it.

Final releases are rebuilt from their tag against the exact package version from PyPI. A release such as `2.1.3` replaces `2.1/`; patch-version directories are not retained. The newest version also replaces `stable/`, while an older maintenance release updates only its own minor directory. Prereleases are not published.

Python wheels are published by a separate, approval-gated pipeline. If the exact package version is not on PyPI when the GitHub release is published, the Docs workflow fails with a direct error and should be rerun after the wheel is available.

Manual runs (`workflow_dispatch`) choose the source ref and exact package version. They derive the minor-version target automatically and default to a non-publishing build, which is how older final releases can be validated or backfilled.

On the first release publish, the site assembler removes the previous flat Sphinx tree only after `stable/` exists. This keeps the current site available if `develop/` is published before the first release migration.

All minor versions are retained. A build is currently about 50 MB and GitHub Pages limits a published site to 1 GB, so site size must be monitored as the number of minor releases approaches that limit.

Two environment variables let a build target a specific version directory, and are set by the workflow:

- `QDK_CHEMISTRY_DOCS_VERSION` overrides the version label taken from the [`VERSION`](../VERSION) file.
- `QDK_CHEMISTRY_DOCS_BASE_URL` sets the canonical URL of the build.

The site assembler records the source ref, commit, documentation version, exact package version, and build time in each published directory's `.build-info.json`.
