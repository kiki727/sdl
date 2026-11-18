# archive/

Everything in this directory is **historical**. Nothing here is imported by the
`sdl` package, is executed by the test suite, or is part of the current build.

If you are looking for the current specification, it is `spec/sdl-core-1.0.md`.
If you are looking for the current implementation, it is `sdl/`.

## specs/

Historical specifications, preserved verbatim and **not** edited.

| File | Core | Status | Why it is kept |
| :--- | :--- | :--- | :--- |
| `sdl-core-0.1.md` | 0.1 | Superseded | Initial formal draft. Useful as design history. |
| `sdl-core-0.2.md` | 0.2 | Superseded, **normative baseline** | Core 1.0 inherits every 0.2 rule. This is the specification the conformance suite in `conformance/0.2/` tests against. |
| `sdl-core-0.3.md` | 0.3 | Superseded, never released | The text that became Core 1.0. Kept so the rename in `spec/sdl-core-1.0-changelog.md` can be diffed against its original. |
| `canonical-ir-v0.1.md` | — | Superseded design note | An early description of the Canonical IR as a typed, attributed, directed symbol graph. Superseded by section 9 of the Core 1.0 specification. Kept because it introduces the symbol and edge model in a shorter form. |

The 0.2 specification lists machine-verifiable artifact paths that have since
moved. Those deviations are recorded as errata in `spec/VERSIONING.md` §5, not
by editing the frozen text.

## notes/

Working documents from the design phase.

| File | Contents |
| :--- | :--- |
| `prompt-master.txt` | The master implementation prompt used to drive the original v1.0 build. Describes the intended layer breakdown, the error-code registry, and the security requirements. Some of it was not implemented; treat it as intent, not as a description of the code. |
| `review-kritika.txt` | An external review of Core 0.3 and a critique of the architecture. Most of its findings are still open and are tracked by the milestones in the README. |

## legacy/

Superseded tooling.

| File | Why it is archived |
| :--- | :--- |
| `verification_suite_gemmini.py` | A self-contained reimplementation of the verification suite that does **not** import the `sdl` package — it re-declares the IR classes and simulates the proposal rules inline. It was never wired into the build and does not test the real implementation. The live suite is `tests/`. |
