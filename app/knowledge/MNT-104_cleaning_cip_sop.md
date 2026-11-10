# MNT-104 Scheduled line cleaning (CIP)

*Fictional example document for the Plant Ops Copilot demo.*

## 1. Schedule
A cleaning-in-place cycle of about 10 minutes runs at 09:00 during the shift. All machines report the state CLEAN during that time.

## 2. Effect on data
During CLEAN the motor current and vibration drop to idle values and the cycle time is not defined. This is expected and not an anomaly. CLEAN time is excluded from availability calculations.

## 3. After cleaning
Temperatures may be a little lower for a few minutes after cleaning because of rinse water. If a signal does not return to its previous level within 15 minutes, investigate.
