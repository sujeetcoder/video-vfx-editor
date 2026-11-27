# Recovery: kill-mid-transcribe

Kill the process during asr.py (Ctrl+C). Expected: no partial words.json, state.json still at cut, `forge.py resume` points at asr again, one CPU retry is not counted as a new failure.
