# Odin — Contributor Docs

The repo-root [`README.md`](../README.md) is the operator manual. This directory is for contributors changing code.

| Doc | Read this when… |
|---|---|
| [`backend.md`](./backend.md) | Touching anything under `src/odin/` other than templates / static. |
| [`frontend.md`](./frontend.md) | Touching templates, CSS, JS, or the SSE consumer. |
| [`configuration.md`](./configuration.md) | Changing `pyproject.toml`, `Makefile`, `Dockerfile`, `compose/` files, or `config/gunicorn.conf.py`. |
| [`searxng.md`](./searxng.md) | Changing `searxng/settings.yml` or debugging search. |
| [`claude-api.md`](./claude-api.md) | Adding or modifying an Anthropic API call. |
| [`coding-standards.md`](./coding-standards.md) | The rubric for *how* we write code (linked from [`CLAUDE.md`](../CLAUDE.md)). |

New here? Read `backend.md` first — the pipeline is the heart of the project.
