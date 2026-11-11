# Aegis Mobile roadmap

The previous Personal Insight roadmap is superseded. This is a plan, not a record of implemented features.

## Milestone 1 — immediate priority

1. Finalize the six-screen mobile scope.
2. Create editable Figma wireframes.
3. Produce matching high-fidelity mockups.
4. Link the prototype and verify main, failed-verification and existing-PR paths.
5. Export the 1–2 page design justification, user-flow PDF, and architecture/protocols PDF.
6. Add final Figma links and PDFs to the repository.
7. Check instructor access, update the class sheet, package the repository and upload to the course portal.

See [submission checklist](SUBMISSION_CHECKLIST.md) for acceptance checks.

## Subsequent implementation phases

| Phase | Planned result | Acceptance criterion |
|---|---|---|
| Flutter foundation | MVVM structure, navigation and fixture data | All six screens reachable with loading/empty/error states |
| Backend integration | Status, incident results and foreground events | Client handles real JSON, reconnects and labels source/freshness |
| Local data | Cached summaries; optional saved notes/bookmarks | Bounded offline access and persistence after restart |
| Remote access | Authentication, authorization and durable incident state | User access is enforced; service credentials stay server-side |
| Evidence and review | Verified result display and confirmed GitHub links | Simulation, verification and deployment are not conflated |
| Quality and delivery | Device tests, documentation and demonstration | Core flow works; failures and offline behavior are demonstrated |

Exact final-project dates and grading requirements should be checked against current course materials before implementation.

## Decisions still open

- Figma links and assigned individual/team number.
- State-management library and local persistence library.
- Authentication provider and backend ownership rules.
- Durable incident storage and reliable typed progress messages.
- Scope of optional notes/bookmarks and synchronization.
- Whether manual remediation belongs in the first mobile implementation or only incident viewing.

## Deferred scope

Background push notifications, in-app PR merging, automatic production deployment, billing, team administration and broad backend configuration.

## Evidence rule

Do not claim an implementation, successful test, live PR or production improvement until it has actually been verified. Upstream example results remain attributed examples.
