# MNT-106 Machine states and availability

*Fictional example document for the Plant Ops Copilot demo.*

## 1. State definitions
RUN: the machine is producing. IDLE: the machine is waiting (starved or blocked), a normal short stop. FAULT: the machine stopped because of an alarm or protective trip. CLEAN: scheduled cleaning.

## 2. Availability
Availability is RUN time divided by the total time without CLEAN. A healthy machine is above 95 %. Below 90 % needs investigation. IDLE periods of one to four minutes a few times per shift are normal.

## 3. Reading fault events
Single FAULT events of 30 to 90 seconds late in a degradation trend are micro-stops caused by the degrading component. Repeated FAULT events of about 10 minutes with regular spacing indicate a protective function tripping again and again.
