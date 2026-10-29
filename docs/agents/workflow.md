# Agent workflow

How a ticket goes from ready to merged in this repo. Ticket operations are in `docs/agents/issue-tracker.md`, and state labels are in `docs/agents/triage-labels.md`. The `ship-ticket` skill runs this workflow.

## Definition of Ready

An agent may move a ticket to `ready-for-agent` on its own only when every item holds. Otherwise it moves the ticket to `needs-info` and posts its questions as a comment.

1. The outcome is stated in 1–3 sentences.
2. Every acceptance criterion names its proof: "running X against Y shows Z".
3. The ticket is a clear, shippable increment with defined seams (design and API contracts). Every question is answered, so the agent can choose freely how to build it.
4. The tickets it depends on are linked, and are done or safe to work on in parallel.
5. No product question is open. If one is, the ticket goes to `needs-info` or `ready-for-human`.
6. Out-of-scope items are listed wherever the scope could be read two ways.

## Definition of Done

1. The CI check `verify` (`just verify`) passes on a branch that is up to date with `main`.
2. The PR maps every acceptance criterion to its proof: a test name, a command output, or the demo.
3. A demo is attached wherever tests do not show the behaviour.
4. The local cross-family adversarial review ran before the PR. Findings left unfixed are listed under "Known limitations".
5. Every review thread is resolved: fixed, or rebutted with a reason in the thread. If threads remain open after 3 review rounds, the PR gets a stalemate note and the ticket goes to `ready-for-human`.
6. Docs are updated for the changed area.
7. The PR links the ticket (`Fixes #N` on GitHub Issues). The squash commit carries the trailers `Ticket:` and `Agent:`.

## Evidence

- The PR adds only what CI and the review threads cannot show: which proof covers which criterion, the demo, and the deviations.
- Demos use fixture or sample data and repo-relative paths. They show no real personal data and no secrets.

## Filing rule

While working, file a new ticket only for work you will not do now and that is larger than about 30 minutes. Do smaller work in place, or name it under "Deviations and known limitations".

## Merge gate

`main` accepts only squash merges of PRs whose `verify` check passed on an up-to-date branch and whose conversations are all resolved. The gate binds administrators too. Agents merge with auto-merge.
