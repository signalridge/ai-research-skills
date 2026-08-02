# alpha2025iterative — notes

*Illustrative example.*

## Method
Iterative retrieve-then-reason loop, re-querying after each hop with the partial answer
appended. Stops on a confidence threshold or 4 hops.

## What the ablations actually show
§5.2 varies context length for the long-context arm while holding the retriever fixed.
The 6.2 EM gap at 8k shrinks to 1.8 EM at 64k. The paper reads this as "retrieval still
wins"; it is equally consistent with "the gap is an artifact of context starvation."

## What it does not do
Never reports retrieval recall for either arm. Both arms are given the same *token* budget,
which means the retrieval arm may be seeing strictly more relevant evidence per token. This
is the hole G1 sits in.

## Reproducibility
Official repo, ran the 2-hop config to within 0.3 EM of the reported number. `runs: verified`.
