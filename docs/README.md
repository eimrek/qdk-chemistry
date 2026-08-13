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

## Publishing the documentation

The published site is served by GitHub Pages from the `docs/` directory of the `gh-pages` branch, and holds one directory per documentation version:

```text
docs/
  index.html      redirect to stable/
  404.html        rewrites legacy flat paths into stable/
  switcher.json   version list for the theme version switcher
  latest/         tip of main
  stable/         copy of the newest release
  2.1.0/  ...     one directory per release
```

The [`Docs`](../.github/workflows/docs.yaml) workflow maintains it, and [`.github/scripts/docs_site.py`](../.github/scripts/docs_site.py) does the site assembly.

`latest/` is republished automatically after every successful `Build and Test` run on `main`, reusing the documentation that workflow already builds rather than rebuilding it.

On a published release the workflow publishes `<version>/` and `stable/` from the documentation built for the tagged commit, in this order of preference:

1. copy `latest/`, if it still points at the tagged commit;
2. otherwise recover it from `gh-pages` history, since every `latest/` publish records the commit it was built from in `.build-info.json`;
3. otherwise rebuild it against the released package from PyPI.

Manual runs (`workflow_dispatch`) choose the source ref, the target directory and whether to publish at all, which is how older releases are backfilled.

Two environment variables let a build target a specific version directory, and are set by the workflow:

- `QDK_CHEMISTRY_DOCS_VERSION` overrides the version label taken from the [`VERSION`](../VERSION) file.
- `QDK_CHEMISTRY_DOCS_BASE_URL` sets the canonical URL of the build.
