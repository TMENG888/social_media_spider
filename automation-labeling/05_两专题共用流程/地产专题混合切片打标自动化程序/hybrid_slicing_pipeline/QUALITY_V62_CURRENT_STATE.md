# Current quality work, 2026-10-10

The goal is still incomplete: fixed random 24 articles and all 36 comments,
two delivery sheets, semantic audit and saved-cell/visual verification.
No samples substituted and no manual delivery-row repairs.

## Confirmed evidence

- v58 full batch terminal, 60 sources, 143 all-manual rows; not acceptable.
- v59 six-source smoke terminal; not acceptable.
- v60a six-source smoke terminal, 32 rows, 21 blank prose, comparison article
  incomplete. Aggregate audit saved in its result folder. Missing-source checks
  outside these six are not smoke semantic failures, but full scope not proven.
- v61 six-source smoke session59344 is now terminal exit0:32 all-manual rows,
  comparison article incomplete,127 new logical calls, known new estimate
  0.06311716 yuan,30 unknown usage/price calls. Still not acceptable.
- v61 comment summaries now retain both authors and geographic qualifiers;
  product prose still often null, and comment project targets rejected.

## Root cause found and fixed in v62, not yet real-tested

`bounded_visible_contract_v60.contract` used deepcopy on schemas assembled from
shared KEYS objects. deepcopy preserves shared identity. Walking comment_keys then
parent_identity_keys overwrote both fields with the PARENT enum. Reproduced directly:
comment_keys allowed PARENT keys; model followed this invalid contract, and literal
verifier correctly rejected the generated project evidence.

New isolated entrypoint `delivery_v62.py` de-aliases the schema by JSON roundtrip
before adding evidence namespaces. Tests require disjoint COMMENT/PARENT enums,
unchanged source schema, and rejection of null prose with nonempty factual claims.
Generation schema permits null only with empty claims, while genuine no-fact/low
confidence responses remain allowed. It does not increase confidence or approve
semantics. Explicitly explains output_field and prose vs claims to the model.

888 runnable offline tests passed, legacy test_concurrency excluded because it
needs missing sklearn; these tests are not evidence of real label accuracy.

## Prepared next run

`test_results_v11_62_full_random_20261009_api` frozen snapshot prepared using v61
five-source current_snapshot plus all exact call caches at preparation time.
Do not overwrite snapshot. v62 smoke started after v61 was confirmed terminal.
Use the new exec session reported in conversation to check its actual liveness;
key was read securely from User environment. Never print/store/chat the key.

Actual v62 exec session is63965. At last poll it is live,4/6 completed. Do not
restart while live. Three comments already independently read from snapshot:
7279 now retains保利熙瑞/西冉地块 and both authors'qualified opinions;7188 leaves
ambiguous targets empty. **7185 wrongly maps explicitly named西冉地块 to保利熙瑞**.
Its raw proposal calls this parent_relation with0.95, using a parent sentence
that mentions both projects. Literal-key validation cannot prove the relationship.
This is a genuine semantic false association, not a schema issue. Requires
independent project relationship check before acceptance, not manually fixing row.
Do not extrapolate v62 as successful based on recovery of project fields.

Six IDs: T1-182247585093626012, T1-2944395937563134382,
T2-2188228096999350274, T2-C-7963753211120747185,
T2-C-7963753211120747279, T2-C-7963753211120747188.

After meaningful smoke improvement, process all fixed60 and independently audit
remaining missed/wrong labels and granularity. Workbook not yet created; do not
claim completion. Default delivery_v11 launcher still originalv58; new entrypoints
activate hooks only in their own process. Prep and snapshot tools now support v62.
