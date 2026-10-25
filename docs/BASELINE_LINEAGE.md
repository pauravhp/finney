# Frozen comparison references

A benchmark may run in an event that has no active skill, or whose active skill
has different content. It now stores the exact bundled baseline as a private,
non-active `baseline_reference` version before creating candidate and evaluation
records. An active version is reused only when its content hash matches. This
never initializes or changes the event's active skill.

The Learning view loads the linked baseline and candidate artifacts on demand,
checks their scope and content hashes, and displays the stored procedure diff.
Missing baseline references are shown explicitly; a candidate download alone is
not presented as a comparison.

Focused fixtures cover absent, different and matching active versions, and an
artifact hash mismatch. Historical missing references can be repaired separately
only against verified frozen artifacts after an experiment is terminal. Such a
repair must be audited and preserve scores, outputs, status, metrics and active
skills. It is metadata maintenance, not a new learning result.
