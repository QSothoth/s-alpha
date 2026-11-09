#!/bin/bash
# Wrap the workflow script as a function and run the mock scenarios against fake agents.
cd "$(dirname "$0")"
WF=../../../../.claude/workflows/trader-replication-loop.js
{ echo '(async function(args,agent,parallel,pipeline,phase,log){'; sed 's/^export const meta/const meta/' "$WF"; echo '})'; } > wfcheck.js
node mock2.js && node mock3.js
