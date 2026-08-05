---
description: Build/adopt/skip decision brief from a completed survey
argument-hint: "<the decision you are making>"
---

Run the `rs-decision-brief` skill for: **$ARGUMENTS**

Ask for the decision context first — what is being built, what the alternative is, what the
cost of being wrong is. A brief written without it answers a question nobody asked.

Weight evidence by reproducibility, not venue: a reproduced arXiv preprint beats an
unreproduced NeurIPS oral. `code.runs: verified` outranks everything else.

Include the rows with **no** support — a claim the design depends on that nobody has
established is the most valuable line in the table. Cross-reference `gaps.yml`.

Unlike `rs-gap-gate`, do make a recommendation. State the uncertainty in the same breath.
