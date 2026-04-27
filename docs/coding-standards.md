# Coding Standards

The rubric for *how* we write code in this repo. The hard process requirements (write tests first, run `make lint`, run `make test`) live in [`CLAUDE.md`](../CLAUDE.md).

## Expectations

- Define validation criteria before pursuing a task; execute them before calling it done.
- Prefer iteration over complete solutions — find the smallest increment.
- Think thoroughly; output concisely.
- Write commit subject lines that read well in `git log`.

## Software development principles

- Prefer composition over inheritance.
- Prefer dependency injection over tight coupling.
- Prefer functional programming over OOP — plain functions and pydantic/dataclass models beat classes with hidden state.
- Prioritize readability over performance.
- Prioritize clarity over comments.
- Only mock third-party dependencies — not our own code.
- Review computational and memory complexity at design time.

## SOLID

- **S**ingle responsibility — one reason to change per module/function.
- **O**pen/closed — open for extension, closed for modification.
- **L**iskov substitution — subtypes must behave like their parents.
- **I**nterface segregation — small interfaces beat large ones.
- **D**ependency inversion — depend on abstractions, not concretions.

## Zen of Python

- Beautiful is better than ugly.
- Explicit is better than implicit.
- Simple is better than complex.
- Complex is better than complicated.
- Flat is better than nested.
- Sparse is better than dense.
- Readability counts.
- Special cases aren't special enough to break the rules.
- Although practicality beats purity.
- Errors should never pass silently.
- Unless explicitly silenced.
- In the face of ambiguity, refuse the temptation to guess.
- There should be one — and preferably only one — obvious way to do it.
- Although that way may not be obvious at first unless you're Dutch.
- Now is better than never.
- Although never is often better than *right* now.
- If the implementation is hard to explain, it's a bad idea.
- If the implementation is easy to explain, it may be a good idea.
- Namespaces are one honking great idea — let's do more of those!
