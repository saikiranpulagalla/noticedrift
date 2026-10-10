# Verdict model

## `SUPPORTED_BY_EVIDENCE`
All comparable supplied critical fields agree with safely resolved governing evidence, evidence coverage is adequate, and no potentially governing source remains unresolved. UI wording should be **Currently supported**, never "verified current".

## `SUPERSEDED`
At least one supplied critical field conclusively differs from an applicable active governing value with complete provenance.

## `CANCELLED`
A full applicable cancellation is proven and no later applicable reopening restores the notice.

## `CONFLICT`
Strong applicable governing branches disagree and precedence cannot safely resolve them.

## `UNRESOLVED`
The system abstains because identity, lineage, applicability, parsing, coverage, or governing state cannot be established safely.

## Asymmetry
One proven applicable change is enough to prove `SUPERSEDED`. Positive support requires broader evidence coverage. Uncertainty may reduce certainty; it may never increase it.
