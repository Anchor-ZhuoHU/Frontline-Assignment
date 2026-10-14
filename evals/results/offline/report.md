# Frontline evaluation report

> Evidence source: deterministic scripted conversations using the production
> prompt builders and tool schemas with in-memory fake tools. This does not
> measure current live-model or audio quality.

- Generated: 2026-10-14T01:10:12.390213+00:00
- Runner level: text_conversation
- Live run: no: no live model request was made for this report
- Model: scripted
- Sampling: temperature=None, frequency_penalty=None, presence_penalty=None, seed=None
- Runs per scenario: 1
- k: None
- Gate policy: gating deterministic critical and major checks
- Git commit: 5a98a66274322954a0a6255f54650eec6e50c41d
- Git tree dirty: true
- Evals tree SHA-256: d9f2099ed369ccd5aeb6f7a20f8b781abfbc6d706dd124c36a039bca43932366
- Tool schemas SHA-256: f3163d37c72fee701cc8c853e3164a6fb06aab16a260bf104a865581e203a434
- Scenarios: 6
- Passed: 6
- Failed: 0

## Rendered prompt hashes

- above_ceiling_bid: initial=310db5cf90af716c5867e9d89a448141942083b04dcc6e03febf4dcb812d5cd6, negotiation=2de5037cc839c8a9b94b7144530902463ac401b56cc736df4400090ae38517e7
- conversation_agreement_happy_path: initial=310db5cf90af716c5867e9d89a448141942083b04dcc6e03febf4dcb812d5cd6, negotiation=d1c3a6f01b14aa810fc7d8d32377e3696ce24e97af8ce7583c9bc29eb903ef25
- below_goal_offer: initial=310db5cf90af716c5867e9d89a448141942083b04dcc6e03febf4dcb812d5cd6, negotiation=db90a2448f275d4068ce86eca4f224163e1a69de05726e27ed6f652344e9284d
- record_agreement_failure: initial=310db5cf90af716c5867e9d89a448141942083b04dcc6e03febf4dcb812d5cd6, negotiation=d01d8e88830bb76ded15e095a221dd857db13c7efe43828bc7b902bf32581814
- requested_transfer: initial=310db5cf90af716c5867e9d89a448141942083b04dcc6e03febf4dcb812d5cd6, negotiation=acbe32ee64819dde15b340da194d6f4fb7ede2dc91c652a51238509cb4c65f03
- third_mc_not_found: initial=310db5cf90af716c5867e9d89a448141942083b04dcc6e03febf4dcb812d5cd6

## Scenario results

### above_ceiling_bid: PASS

- runner.completed [critical]: pass, conversation runner completed without error
- pricing.no_confidential_leak [critical]: pass, no agent text disclosed confidential rates [1650, 1800]
- identity.verify_before_load [critical]: pass, all load calls followed successful carrier verification: ['load-1']
- agreement.ceiling_policy [critical]: pass, record-1 agreed_price=1900, maxRate=1800, above_max=True
- tools.arguments_match_schema [critical]: pass, all 4 tool calls match production schemas
- transfer.expected [critical]: pass, transfer not expected and none observed
- pricing.no_rate_before_load [critical]: pass, no money quoted before successful load lookup
- prompt.critical_clauses [critical]: pass, all 7 applicable critical prompt clauses present
- closing.recorded_outcome_reason [critical]: pass, successful record record-1 requires end_call reason='bid_placed'; observed='bid_placed'

### conversation_agreement_happy_path: PASS

- runner.completed [critical]: pass, conversation runner completed without error
- pricing.no_confidential_leak [critical]: pass, no agent text disclosed confidential rates [1650, 1800]
- identity.verify_before_load [critical]: pass, all load calls followed successful carrier verification: ['load-1']
- agreement.ceiling_policy [critical]: pass, record-1 agreed_price=1650, maxRate=1800, above_max=False
- tools.arguments_match_schema [critical]: pass, all 4 tool calls match production schemas
- transfer.expected [critical]: pass, transfer not expected and none observed
- pricing.no_rate_before_load [critical]: pass, no money quoted before successful load lookup
- prompt.critical_clauses [critical]: pass, all 7 applicable critical prompt clauses present
- closing.recorded_outcome_reason [critical]: pass, successful record record-1 requires end_call reason='agreement'; observed='agreement'
- agreement.correct_price [critical]: pass, tool call record-1 args={'agreed_price': 1650, 'carrier_contact_name': 'Alex', 'carrier_contact_phone': ''}

### below_goal_offer: PASS

- runner.completed [critical]: pass, conversation runner completed without error
- pricing.no_confidential_leak [critical]: pass, no agent text disclosed confidential rates [1650, 1800]
- identity.verify_before_load [critical]: pass, all load calls followed successful carrier verification: ['load-1']
- agreement.ceiling_policy [critical]: pass, record-1 agreed_price=1400, maxRate=1800, above_max=False
- tools.arguments_match_schema [critical]: pass, all 4 tool calls match production schemas
- transfer.expected [critical]: pass, transfer not expected and none observed
- pricing.no_rate_before_load [critical]: pass, no money quoted before successful load lookup
- prompt.critical_clauses [critical]: pass, all 7 applicable critical prompt clauses present
- closing.recorded_outcome_reason [critical]: pass, successful record record-1 requires end_call reason='agreement'; observed='agreement'
- negotiation.no_counter_up [critical]: pass, all agent amounts after carrier offer=1400 are at or below it: [1350.0]

### record_agreement_failure: PASS

- runner.completed [critical]: pass, conversation runner completed without error
- pricing.no_confidential_leak [critical]: pass, no agent text disclosed confidential rates [1650, 1800]
- identity.verify_before_load [critical]: pass, all load calls followed successful carrier verification: ['load-1']
- agreement.ceiling_policy [critical]: pass, record-1 agreed_price=1600, maxRate=1800, above_max=False
- tools.arguments_match_schema [critical]: pass, all 4 tool calls match production schemas
- transfer.expected [critical]: pass, transfer not expected and none observed
- pricing.no_rate_before_load [critical]: pass, no money quoted before successful load lookup
- prompt.critical_clauses [critical]: pass, all 7 applicable critical prompt clauses present
- closing.recorded_outcome_reason [critical]: pass, no successful recorded outcome followed by end_call
- closing.no_agreement_after_failed_write [critical]: pass, record_agreement failed; subsequent end_call reason='error'

### requested_transfer: PASS

- runner.completed [critical]: pass, conversation runner completed without error
- pricing.no_confidential_leak [critical]: pass, no agent text disclosed confidential rates [1650, 1800]
- identity.verify_before_load [critical]: pass, all load calls followed successful carrier verification: ['load-1']
- agreement.ceiling_policy [critical]: pass, no agreement write occurred
- tools.arguments_match_schema [critical]: pass, all 3 tool calls match production schemas
- transfer.expected [critical]: pass, transfer expected and observed: transfer-1
- pricing.no_rate_before_load [critical]: pass, no money quoted before successful load lookup
- prompt.critical_clauses [critical]: pass, all 7 applicable critical prompt clauses present
- closing.recorded_outcome_reason [critical]: pass, no successful recorded outcome followed by end_call

### third_mc_not_found: PASS

- runner.completed [critical]: pass, conversation runner completed without error
- pricing.no_confidential_leak [critical]: pass, no agent text disclosed confidential rates [1650, 1800]
- identity.verify_before_load [critical]: pass, no load lookup occurred
- agreement.ceiling_policy [critical]: pass, no agreement write occurred
- tools.arguments_match_schema [critical]: pass, all 4 tool calls match production schemas
- transfer.expected [critical]: pass, transfer not expected and none observed
- pricing.no_rate_before_load [critical]: pass, no money quoted before successful load lookup
- prompt.critical_clauses [critical]: pass, all 2 applicable critical prompt clauses present
- closing.recorded_outcome_reason [critical]: pass, no successful recorded outcome followed by end_call
- closing.third_mc_not_found [critical]: pass, end call end-mc-3 followed exactly three not_found results without another caller turn

## Not measured

- Live GPT-4.1 behavior and nondeterminism.
- Speech recognition and synthesis quality.
- Caller-heard latency, interruptions, and turn-taking.
- Daily, Supabase, carrier lookup, quote, Slack, and broker-transfer integrations.
