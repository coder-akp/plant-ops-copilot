# MNT-105 Maintenance priority matrix

*Fictional example document for the Plant Ops Copilot demo.*

## 1. Priority definitions
Priority 1 (P1): safety risk, a trip limit reached, or two or more protective trips within one hour. Respond immediately, at the latest within 1 hour. Priority 2 (P2): an alert limit is breached, or the current trend predicts an alert breach within 4 hours. Act at the next planned stop, at the latest within 8 hours. Priority 3 (P3): a drift without a limit breach, or an instrumentation fault outside a protective chain. Act within 3 days. Priority 4 (P4): informational, no action.

## 2. Escalation
Escalate a P2 to P1 if the signal also reaches its trip level or if production stops repeatedly because of it. A P3 instrumentation fault becomes P2 if the affected signal feeds a protective function.

## 3. Work order content
Every work order needs the machine, a short title, the priority, the evidence (signal, values, times), the suspected cause, and the recommended action. Work orders are proposals until a human approves them.
