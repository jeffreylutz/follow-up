# Python Tooling: Package & Environment Managers

A survey of Astral **uv**, **Poetry**, and comparable tools for managing Python
dependencies, virtual environments, builds, and publishing.

_Last updated: June 2026._

---

## TL;DR

- **Starting a new project in 2026?** Use **uv**. It is 10–100× faster than the
  alternatives and replaces a half-dozen tools (pip, pip-tools, pipx, pyenv,
  virtualenv, build, twine) with a single Rust binary.
- **Already on Poetry and happy?** It still works well and isn't going anywhere
  (~66M monthly PyPI downloads, actively maintained). Migrate to uv when speed
  or the multi-tool sprawl starts to hurt.
- **Data science / GPU / ML?** Use **Conda/Mamba** for the environment (it
  handles non-Python binaries and CUDA), then uv or pip inside it for pure-Python
  packages.
- **Avoid for new work:** **Rye** (Astral's predecessor to uv — use uv instead)
  and **Pipenv** (maintenance mode, superseded).

---

## Background: what these tools actually do

It helps to separate two jobs that often get conflated:

| Job | Tools that do it |
|-----|------------------|
| **Install packages** | pip, uv, conda |
| **Manage a project** (deps + lockfile + venv + build + publish) | uv, Poetry, PDM, Hatch, Pipenv |
| **Manage Python interpreter versions** | uv, pyenv, conda, rye |

Modern project managers all read **`pyproject.toml`** (the PEP 517/518/621
standard), and produce a **lockfile** that pins exact transitive versions +
hashes for reproducible installs.

---

## The Tools

### uv (Astral) — the new default

- **What it is:** An extremely fast all-in-one Python package and project
  manager written in Rust. Aims to be "Cargo for Python."
- **Replaces:** pip, pip-tools, pipx, poetry, pyenv, twine, virtualenv — one
  binary for all of it.
- **Speed:** ~10–100× faster than pip/Poetry on cold installs, lockfile
  resolution, and venv creation (e.g. ~3s vs Poetry's ~11s on a cold install
  from lockfile). This is its headline feature.
- **Capabilities:** Dependency resolution, `uv.lock` lockfiles, workspaces
  (monorepos), Python version management (downloads interpreters for you),
  inline script dependencies (PEP 723), and — since v0.4 — native `uv build`
  and `uv publish` for libraries.
- **Backing:** Strongest corporate backing of any Python packaging tool.
  **OpenAI announced its acquisition of Astral on March 19, 2026** (pending
  regulatory approval); Astral previously raised seed/Series A (Accel) and
  Series B (a16z). Now ~75M monthly PyPI downloads, surpassing Poetry.
- **Trade-offs:** The CLI can feel clunky/inconsistent once you move past
  initial setup into day-to-day maintenance. Single-vendor concentration risk
  (uv, Ruff, ty all from one company now inside OpenAI) is a concern for some.

```bash
uv init myproject          # scaffold a project
uv add requests            # add a dependency (updates pyproject.toml + uv.lock)
uv run python main.py      # run inside the managed venv
uv sync                    # install exactly what's in the lockfile
uv python install 3.13     # manage interpreter versions
uv build && uv publish     # build + publish a library
```

### Poetry — the mature incumbent

- **What it is:** A complete project manager: dependency resolution, virtual
  environments, building, and publishing through one CLI. Long the de-facto
  standard before uv.
- **Strengths:** Polished, well-documented UX; historically the smoothest
  publish-to-PyPI workflow; huge install base and ecosystem familiarity;
  `poetry.lock` for reproducibility.
- **Trade-offs:** Significantly slower than uv (roughly 3× on cold installs and
  lockfile generation). Doesn't manage Python interpreter versions itself
  (pair with pyenv). Historically used a non-standard `[tool.poetry]` table,
  though v2.x improved PEP 621 alignment.
- **Status:** Actively maintained (v2.3.2 shipped Feb 2026), ~66M monthly
  downloads. A perfectly reasonable choice, especially for teams already on it.

### PDM — standards-first alternative

- PEP 621-native from the start, with a fast dependency solver.
- Supports PEP 582 (`__pypackages__`, no venv) as well as traditional venvs.
- A solid, standards-aligned pick if you specifically want its design — but
  uv now covers most of the same ground faster and with more momentum.

### Hatch — packaging & test matrices

- Backed by the PyPA (Python Packaging Authority).
- Strongest at **multi-environment testing matrices** (test across many Python
  versions/dependency sets) and as a build backend (`hatchling`).
- Less focused on being your everyday dependency lockfile manager; often used
  alongside other tools or as the build backend in `pyproject.toml`.

### Pipenv — pioneer, now legacy

- Pioneered `Pipfile` / `Pipfile.lock`.
- In 2026 it's in **maintenance mode**: not broken, but superseded by uv/Poetry.
  Don't pick it for new projects.

### Rye — superseded by uv

- An experimental all-in-one manager **created by Astral**, the predecessor to
  uv. The two have converged.
- **Don't start new projects with Rye** — use uv directly.

### Conda / Mamba — the data-science world

- A general **package + environment manager** (not Python-only) that installs
  precompiled binary packages, including non-Python deps and CUDA/GPU stacks —
  something pip/uv can't fully do.
- **Mamba** is a fast C++ reimplementation of the conda solver.
- Best practice: use Conda/Mamba to create the environment (especially for
  ML/GPU), then use uv or pip inside it for pure-Python packages.

### pip (+ venv) — the baseline

- The built-in installer that ships with Python. Not a full project manager:
  no dependency resolution lockfile workflow, no build/publish orchestration on
  its own. Everything above is, in part, an effort to improve on the
  pip + venv + requirements.txt baseline.

---

## Quick comparison

| Tool | Speed | Lockfile | Manages Python versions | Builds & publishes | Best for |
|------|-------|----------|--------------------------|--------------------|----------|
| **uv** | ★★★★★ | `uv.lock` | ✅ | ✅ | Almost everything; the 2026 default |
| **Poetry** | ★★☆☆☆ | `poetry.lock` | ❌ (use pyenv) | ✅ | Existing projects; teams that know it |
| **PDM** | ★★★★☆ | `pdm.lock` | ❌ | ✅ | Standards purists wanting its design |
| **Hatch** | ★★★☆☆ | (limited) | via plugins | ✅ (build backend) | Test matrices, library packaging |
| **Pipenv** | ★★☆☆☆ | `Pipfile.lock` | ❌ | ❌ | Legacy maintenance only |
| **Rye** | ★★★★☆ | `requirements.lock` | ✅ | ✅ | Nothing new — use uv |
| **Conda/Mamba** | ★★★☆☆ | `environment.yml` | ✅ | ⚠️ (conda channels) | Data science, GPU/non-Python deps |
| **pip + venv** | ★★☆☆☆ | ❌ (requirements.txt) | ❌ | ❌ | Minimal/simple scripts, CI baselines |

---

## Recommendations by use case

- **New app or service:** uv.
- **Library you publish to PyPI:** uv (native build/publish since 0.4) or
  Poetry if your team already knows it.
- **Existing Poetry project:** stay unless speed/sprawl is a pain; migration to
  uv is straightforward via `pyproject.toml`.
- **Data science / ML / GPU:** Conda/Mamba for the env + uv/pip inside it.
- **Monorepo / multiple interrelated packages:** uv workspaces.
- **Testing across many Python versions:** Hatch (or uv + a matrix in CI).

---

## Sources

- [uv documentation](https://docs.astral.sh/uv/)
- [uv on GitHub](https://github.com/astral-sh/uv)
- [Astral blog: uv — Python packaging in Rust](https://astral.sh/blog/uv)
- [OpenAI to acquire Astral](https://openai.com/index/openai-to-acquire-astral/)
- [The Register: OpenAI aims for the stars (Astral acquisition)](https://www.theregister.com/2026/03/19/openai_aims_for_the_stars/)
- [uv vs Poetry vs pip: Which Python Package Manager Wins in 2026?](https://www.danilchenko.dev/posts/uv-vs-pip-vs-poetry/)
- [UV vs Poetry: Which Python Package Manager Should You Use? (BSWEN)](https://docs.bswen.com/blog/2026-02-12-uv-vs-poetry/)
- [Python Dependency Management in 2026 (Cuttlesoft)](https://cuttlesoft.com/blog/2026/01/27/python-dependency-management-in-2026/)
- [Best Python Package Managers 2026 (Scopir)](https://scopir.com/posts/best-python-package-managers-2026/)
- [Python environment managers in 2026 (Big Iron)](https://www.bigiron.cc/guides/python-environment-managers-uv-vs-poetry-vs-pyenv-vs-pipenv-vs-conda)
- [Which Python package manager should I use? (pydevtools)](https://pydevtools.com/handbook/explanation/which-python-package-manager-should-i-use/)
- [Python Packaging Best Practices: setuptools, Poetry, and Hatch in 2026 (dasroot)](https://dasroot.net/posts/2026/01/python-packaging-best-practices-setuptools-poetry-hatch/)
- [An unbiased evaluation of environment management and packaging tools (Popkes)](https://alpopkes.com/posts/python/packaging_tools/)
