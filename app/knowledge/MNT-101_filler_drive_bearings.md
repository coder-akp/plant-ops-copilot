# MNT-101 Filler drive bearings: condition monitoring

*Fictional example document for the Plant Ops Copilot demo.*

## 1. Scope
Applies to the main drive motor and gearbox bearings of the rotary filler (FILLER-01).

## 2. Vibration and current limits
Vibration is measured as velocity RMS in mm/s. Normal operation is below 3.0 mm/s. The alert limit is 4.5 mm/s and the trip limit is 7.1 mm/s (stop the machine). Nominal motor current is 14 A; the alert limit is 17.5 A (125 % of nominal) and the trip limit is 21 A.

## 3. Typical bearing wear signature
Bearing wear shows as a slow, monotonic rise of vibration over hours or days. The motor current rises gradually (roughly 10 to 15 % above baseline) and the cycle time stretches slightly. Temperature changes only a little. In late stages the machine starts to stop for short periods (micro-stops) that last 30 to 90 seconds.

## 4. Differential diagnosis
Misalignment gives a steady offset in vibration from the start instead of a drift. Loose mounting gives erratic, spiky vibration. Lubrication starvation gives a faster rise together with a temperature increase. Product jams give short spikes in current and vibration that disappear again, not a persistent drift.

## 5. Recommended actions
First sign of drift, no limit crossed: lubricate according to schedule and plan an inspection within 24 hours. Alert limit crossed: plan bearing replacement at the next planned stop, at the latest within 8 hours (spare part: bearing kit 6209-2RS). Trip level reached: stop the machine and replace the bearing before restart.
