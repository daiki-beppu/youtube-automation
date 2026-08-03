Before changing production code, add the smallest regression test that reproduces the diagnosed failure. Run it and capture evidence that it is red for the predicted reason; also run the nearest existing safety-net tests.

Set structured verdict to `red_confirmed` only when the new test fails for the diagnosed cause while the relevant existing tests remain green. Set `red_mismatch` for a green test, an unrelated failure, or a contradicted prediction; otherwise set `abort`. Never weaken or delete existing checks.
