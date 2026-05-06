# Prose Style Guide

Based on *The Elements of Style* by Strunk & White (4th ed.).

**Apply to prose only** — commit messages, README sections, API docs, release notes, summaries, and any human-facing text. Not for code comments (see `coding-standards.md`).

---

## Core rules

**Active voice.** Say who does what.
- Weak: `The token is validated by the server.`
- Strong: `The server validates the token.`

**Positive form.** State what is, not what is not.
- Weak: `The method does not return null.`
- Strong: `The method always returns a value.`

**Omit needless words.** Cut on sight: `the fact that`, `in order to`, `at this point in time`, `it is important to note that`, `currently` (with present tense), `respective(ly)`, `and/or`.

**Concrete over vague.** Replace generalities with specifics.
- Vague: `There may be performance issues.`
- Specific: `Requests over 10 MB time out after 30 seconds.`

**Emphatic words at the end.** The end of a sentence carries the most weight. Put the key point there.

**Parallel construction.** Items in a list or pair must share the same grammatical form.
- Wrong: `Supports parsing, to validate, and running tests.`
- Right: `Supports parsing, validating, and running tests.`

**One tense.** Pick present or past; do not shift. Use perfect tenses only for prior/subsequent action within that frame.

**No qualifiers.** Cut `very`, `quite`, `rather`, `pretty`, `little` unless they carry exact meaning.

**No overstatement.** One superlative that cannot be defended undermines everything around it.

---

## Punctuation

- **Serial comma:** `read, parse, and validate` — comma before the conjunction.
- **Comma splice:** Two independent clauses need a semicolon, period, or conjunction — not just a comma.
- **Colon:** Only after a complete clause. `Three fields are required: name, email, role.` Not `The fields are: …`
- **Possessive:** Always add `'s`, even after a final `s`. `the class's method`.
- **`that` vs. `which`:** `that` restricts (no commas); `which` adds (commas required).

---

## Words to avoid

| Avoid | Use instead |
|---|---|
| `utilize` | `use` |
| `finalize` | `complete`, `finish` |
| `leverage` (verb) | `use`, `apply` |
| `impactful` | `significant` |
| `ongoing` | `continuing` (or cut) |
| `in terms of` | rewrite |
| `meaningful` | say what it means |
| `hopefully` (dangling) | `I hope`, `we expect` |
| `-ize` coinages | use the plain verb |
| `-wise` suffix | rewrite |

---

## Style reminders

- Write with nouns and verbs; adjectives and adverbs support, they do not carry.
- Do not explain too much. Skip preambles like `It is worth noting that…`
- Avoid fancy words. Prefer `use` over `utilize`, `end` over `terminate`, `show` over `demonstrate`.
- Do not inject opinion unless opinion is the purpose.
- Spell out acronyms on first use.
- When a sentence becomes tangled, start over — break it in two.
- Be clear above all else. Ambiguous documentation causes real harm.
