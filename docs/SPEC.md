# NoticeDrift Contract v0.1

NoticeDrift evaluates whether critical actionable fields in a supplied notice remain supported by the authoritative evidence it successfully retrieves and resolves.

## Non-claims

- Search is not exhaustive.
- Missing search results do not prove that no update exists.
- `SUPPORTED_BY_EVIDENCE` is scoped to retrieved and safely evaluated evidence.
- Weak family binding never governs.
- Unsupported/failed parsing of a potentially governing source blocks positive assurance.
- Unknown applicability never broadens to all users/posts/categories.
- An LLM, if added later, may propose structured extraction only; it never decides the final verdict.

## Verdicts

- `SUPPORTED_BY_EVIDENCE`: all comparable input fields agree with resolved governing evidence and coverage is adequate.
- `SUPERSEDED`: at least one comparable input field conclusively differs from governing evidence.
- `CANCELLED`: an applicable full cancellation is proven and no later applicable reopening supersedes it.
- `CONFLICT`: applicable governing evidence conflicts and precedence cannot be safely established.
- `UNRESOLVED`: identity, applicability, parser coverage, or governing state cannot be safely established.
