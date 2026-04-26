# IMPORTANT REQUIREMENTS

- Before you make a change to the code, write a test for the change you plan. Confirm this test with me before implementing the feature.
- Run linters using `make lint` and ensure they pass before considering a task done
- Run automated tests using `make test` and ensure they pass before considering a task done

# Expectations

- Define the validation criteria for each goal before pursuing each task
- Execute that validation criteria before considering the task complete
- Try to identify the smallest increment of work for each task; prefer iteration over complete solutions
- Think through work thoroughly, keep output concise and clear
- When writing git commits, include a useful subject line that makes the history easy to read


# Software Development Philosophical Goals

- Prefer composition over inheritance
- Prefer dependency injection to tight coupling
- Prefer functional programming to object oriented programming 
- Prioritize readibility over performance
- Prioritize clarity of code over commented code
- Only mock 3rd party dependencies, not our own code; it's okay for unit tests to depend on our own dependencies
- Review computational and memory complexity when designing solutions
- Adhere to SOLID principles:
    - Single responsibility
    - Open–closed
    - Liskov substitution
    - Interface segregation
    - Dependency inversion
- Adhere to the Zen of Python:
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
    - There should be one-- and preferably only one --obvious way to do it.
    - Although that way may not be obvious at first unless you're Dutch.
    - Now is better than never.
    - Although never is often better than *right* now.
    - If the implementation is hard to explain, it's a bad idea.
    - If the implementation is easy to explain, it may be a good idea.
    - Namespaces are one honking great idea -- let's do more of those!
