# Project guidance

This repository evaluates Protenix structure predictions. Use Git for changes and Pixi for the environment. Run prediction and GPU checks only through Slurm on AWS; verify the GPU node stops after use.

## Code Review Rules

### Generality across valid inputs

- Treat behavior tied to a sample sequence, target name, fixture path, fixed input count or shape, output snapshot, or the current test data as a P1 issue unless it is an explicit, documented domain constraint. The implementation must handle the documented class of valid Protenix inputs and supported model options. Ask for the domain reason and identify a different valid input that would fail.
- Check that validation exercises distinct valid inputs and relevant boundary conditions, not only the example used during implementation. Tests must assert meaningful behavior rather than hard-coded fixture output. A test passing only because code recognizes its own fixture is a P1 issue.

### No hidden bypasses

- Treat broad exception handlers, silent defaults, cached or precomputed answers, placeholder structures, skipped prediction stages, or fallback branches that report success after a real failure as P1 issues. Fail visibly with useful context unless a scientifically valid fallback is explicitly documented, surfaced to the user, and tested on independent inputs.
- Check that a change does not remove, weaken, or conditionally skip validation, CI, review, or GPU checks merely to pass a request or test. Any exception must state its scope and reason and preserve a detectable failure signal.

### Review report

- Evaluate these points for every PR: (1) input and model generality beyond the development example; (2) hidden fallbacks or skipped work that could report false success; (3) independent validation, boundary cases, and observable failure behavior; (4) consequential syntax or configuration problems not caught by CI.
- In the review response, list each point with a brief finding, `no P0/P1 issue found`, or `not applicable`, and state the evidence or limitation. For an actionable issue, cite the file and line, give a different input or failure scenario that exposes it, and assign severity. Do not claim a test ran or that correctness is proven without evidence.
