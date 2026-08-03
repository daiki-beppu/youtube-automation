Remove the diagnosed root cause with the smallest coherent change. Make the confirmed red regression test green, preserve the nearby safety net, and do not broaden scope to unrelated findings.

Set structured verdict to `repaired` only with command evidence for the regression and safety-net tests. Set `rediagnose` if the repair contradicts the diagnosis or requires a different causal explanation; otherwise set `abort`.
