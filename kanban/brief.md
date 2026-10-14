Mode: review only

# Brief

Review PR #1, `COR-4078: Migrate voice calls and warm transfers to LiveKit/Telnyx`.

- Base: `5a98a66274322954a0a6255f54650eec6e50c41d`
- Head: `f93f7a5f79efdf08c18c583a6a6f7167084b93ae`
- Deliverable: `REVIEW.md` in the checkpointed workspace root
- Source checkout: `/tmp/frontline-assignment-clone`, read-only review
- Constraints: do not modify either branch, use no production credentials or live calls, separate verified defects from risks and questions.

The PR replaces Daily with LiveKit/Telnyx, keeps the single-prompt agent, and adds a two-room warm transfer. Review readiness includes normal-call parity, transfer safety, SDK compatibility, PII handling, deployment cutover, and rollback.
