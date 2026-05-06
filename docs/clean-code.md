# Clean Code Reference

Based on *Clean Code* by Robert C. Martin.

**Apply to design decisions** — naming, function design, class structure, error handling, and testing. Use during code review, refactoring, or any evaluation of code structure.

---

## When writing code, check each item

**Names**
- [ ] Does every name reveal intent without needing a comment to explain it?
- [ ] One word per concept — no mixing `fetch`, `get`, and `retrieve` for the same operation.
- [ ] No type or scope encodings (`m_`, `i_`, Hungarian notation).
- [ ] Classes are nouns; functions are verbs.
- [ ] Does the name describe what the function does *including its side effects*?

**Functions**
- [ ] Does this function do exactly one thing? Can you extract another meaningful function from it?
- [ ] Do all statements inside operate at the same level of abstraction?
- [ ] Fewer than three arguments; if more, group them into an object.
- [ ] No flag (boolean) arguments — split into two functions.
- [ ] No output arguments — if state must change, change it on `self`/`this`.
- [ ] Does the function either change state or return a value, but not both (CQS)?
- [ ] Is error handling extracted into its own function?

**Comments**
- [ ] Can the comment be eliminated by renaming or extracting?
- [ ] Is this comment explaining *why* rather than *what*?
- [ ] No commented-out code (version control holds the history).

**Classes**
- [ ] Can you describe this class without using "and" or "or"?
- [ ] Does each method use most of the class's instance variables (high cohesion)?
- [ ] Does adding a new behavior require editing this class, or adding a new one (OCP)?
- [ ] Does this class construct its own dependencies, or receive them (DIP)?

**Error handling**
- [ ] Exceptions, not return codes or sentinel values.
- [ ] Does every exception message include enough context to locate the failure?
- [ ] No null returns and no null arguments — use a Special Case object or throw.

**Tests**
- [ ] Do tests exist before or alongside this code?
- [ ] Does each test cover one concept?
- [ ] Are tests fast, independent, and self-validating (no manual log-reading)?
- [ ] Are boundary conditions tested explicitly?

**Before finishing**
- [ ] Is any code duplicated? Every piece of knowledge has one authoritative representation.
- [ ] Is there dead code (unreachable branches, unused functions, commented-out blocks)? Delete it.
- [ ] Can the system's behavior still be verified — does it run all tests?

---

## Core principles (for design decisions)

**Kent Beck's 4 Rules of Simple Design** — in priority order:

1. Runs all tests. Testability drives good decoupling.
2. No duplication. Replace repeated switch/case chains with polymorphism.
3. Expresses intent. Names and small functions eliminate the need to read every line.
4. Minimizes classes and methods. SRP is not a license to create unlimited micro-classes.

**Key structural rules**

- Functions: 2–4 lines; the name describes the abstraction one level above the body.
- Classes: one reason to change (SRP); high cohesion; depend on abstractions (DIP).
- Objects hide data and expose behavior. Data structures expose data and have no behavior. Never mix the two in the same type.
- Law of Demeter: call only methods on `self`, arguments, objects you create, or direct components. Avoid `a.getB().getC().doSomething()`.
- Separate construction from use. `main` (or a factory) builds the object graph; the application uses it.

---

## Common smells and fixes

| Smell | Fix |
|---|---|
| Flag argument | Split into two functions |
| Output argument | Change state on `self`/`this` instead |
| Magic number | Replace with a named constant |
| Commented-out code | Delete it |
| Feature envy (method uses another class's data more than its own) | Move the method |
| Negative conditional (`!buffer.shouldNotCompact()`) | Invert to positive form |
| Train wreck (`a.getB().getC().act()`) | Add a method to the nearest collaborator |
| Hidden temporal coupling (B must run before C) | Make B return a value that C requires |
| Repeated switch/case across modules | Replace with polymorphism |
| Configurable constant buried deep | Lift it to the highest level that knows about it |
