# Current evidence, 2026-10-10

Goal remains incomplete: fixed random24 articles plus all36 associated comments,
then exact two-sheet workbook with source/dictionary/saved-cell/visual checks.
Do not replace difficult sources, repair delivery rows by hand, or use confidence
as measured accuracy. No subagents. No final workbook created.

Previous security-only goal turn was no progress. This turn revalidated session
19330 as terminal exit0 and made code/test/API progress.

## Processes: always revalidate the handle

- v66 session19330 terminal exit0: 33 rows, all manual, one incomplete comparison.
- v67 session52230 terminal exit0: 33 rows, all manual, one incomplete comparison.
- v68 session73420 terminal exit0: 33 rows, all manual, one incomplete comparison.
- v69 session44657 terminal exit0, verified by write_stdin. All6 checkpoints:
  33 rows, all manual, one incomplete comparison. No runner remains live.

Current folder: test_results_v11_69_full_random_20261009_api.
Fixed full sample: test_results_v10_random_20261009_api/fresh_sample.json.
Six-source smoke is still the same3 articles/3 comments listed in earlier notes.

## Findings and edits

- v66 comparison full-source boundaries rejected because literal start_phrase
  crossed catalogue entries; fallback preserved old23 opinion rows. Raw10-group
  proposal also combined garden and clubhouse despite physical-object guidance.
- v67 max24-character anchor schema and stronger physical-object prompt did not
  solve this: model repeatedly emitted a long whole sentence, structural recovery
  repeated it, so comparison boundaries were not adopted. Prompt alone is weak.
- v68 added independent full-source boundary review. Two valid article drafts
  received review, but invalid comparison draft did not: bounded reviewer returns
  raw=None after structure failure, so wrapper prematurely returned. Real result
  still contains overfine parameter/explanation splits and mixed facilities.
- v69 fixes this specific control-flow bug: when API calls all succeeded, recover
  the unmodified invalid proposal from raw audit ONLY as review input. Never accept
  it as final. Independent revised plan still must pass exact schema and literal
  position checks. API failures/auth failures do not trigger this recovery.
- v67/68/69 are separate entrypoints activating runtime hooks; default delivery_v11
  remains oldv58. Do not claim default launcher updated. Frozen snapshots preserved.
- prepare_quality_run_v52.py and snapshot_current_v11.py support throughv69.

908 runnable regression tests passed beforev69 (legacy test_concurrency excluded
for unavailable sklearn; existing active cap tests included). Newv69 plusv68/v67
tests:7 passed. Full regression must be rerun afterv69 and real semantics reviewed.

v66 aggregate_audit_v66.json saved: contract/dictionary checks pass, but garden/
clubhouse mixing, repeated bathroom scheme/correction,3blank summaries and known
recall/precision flaws remain. Missing fixed-source diagnostics in six-source
smoke are expected full-batch checks, not actual omissions in full sample.

## Next work

1 v69 actual independent comparison calls confirmed HTTP200 (2new calls,
  known fee0.0096178yuan). Review and structural recovery still repeatedly return
  the same overlong unit9 anchor and retain parameter/explanation fragmentation
  and garden/clubhouse mixing. Thus the control-flow fix is real, but prompt-only
  boundary optimization has NOT succeeded. Do not repeat the same prompts as
  meaningful progress; change the model-visible decision/position protocol.
  Test whether separate semantic object-range decisions plus a source-position
  resolution stage can reliably locate the model-decided boundaries; never use
  keywords/sentence windows to dictate final semantic boundaries or hand-edit rows.
2 Known unresolved cases: 0146机场 falsely from机场高速;0144road missing in7279;
  park0403 recall; bathroom correction repeats object; sealant fact may be bundled
  with closing invitation; clear西冉地块 comment target7185 lost after rejecting
  wrong保利熙瑞 identity. Definite identities must not be invented from parent.
3 Review boundary-specific recovery errors honestly; don't run all60 until smoke
  meaningfully usable, but eventual completion requires all fixed60, not just6.
4 Final exact product19/opinion20 workbook, two sheets only; savedcell + render
  checks. Spreadsheet skill marker already run earlier; read applicable refs.

Key is configured in User YS_LLM_API_KEY. Read it securely into process env, never
print or save it. API192.168.0.200:3000/qwen3.7-flash/sharedcap10/timeout120/retries2.
Mapping articleid equals original commentCSV文章id; parentODS PK separate trace.
