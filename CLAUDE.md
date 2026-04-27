# IMPORTANT REQUIREMENTS

- Before you make a change to the code, write a test for the change you plan. Confirm this test with me before implementing the feature.
- Run linters using `make lint` and ensure they pass before considering a task done.
- Run automated tests using `make test` and ensure they pass before considering a task done.

# Process expectations

- Define the validation criteria for each goal before pursuing each task, and execute that criteria before considering it complete.
- Identify the smallest increment of work; prefer iteration over complete solutions.
- Think through work thoroughly, keep output concise and clear.
- When writing git commits, include a useful subject line that makes the history easy to read, do NOT use dashes to create lines around the commit messages
- When we add new components, dependencies, or tools to the project, review existing documentation and make updates if necessary, when unsure about what to add: ask

# Coding standards & project orientation

The full rubric (composition, DI, FP, SOLID, Zen of Python) lives in [`docs/coding-standards.md`](./docs/coding-standards.md).

For "where do I find what" in the codebase — back-end, front-end, configuration, SearXNG, the Anthropic API — start at [`docs/README.md`](./docs/README.md).
