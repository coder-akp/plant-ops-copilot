# MNT-103 Sensor and instrumentation diagnostics

*Fictional example document for the Plant Ops Copilot demo.*

## 1. Why sensor signals go wrong
Temperature sensors (RTD or thermocouple) fail because of loose terminals, damaged cables, moisture, or a faulty analog input channel. The result is a bad measurement, not necessarily a bad machine.

## 2. Stuck-at (flatline) signature
A real temperature always shows some noise, typically a few tenths of a degree. A value that stays identical to the last digit for more than 5 minutes while the machine runs is a stuck sensor or a frozen value in the PLC or historian. Cross-check related signals: if motor current and vibration are normal and nothing changed in the process, the cause is the instrumentation and not the machine.

## 3. Dropout signature
Missing samples (null or NaN) are usually abrupt. Common causes are a loose connector, a broken wire, or a communication fault between the PLC and the historian. A stuck period that ends in a dropout often points to the same wiring or channel problem getting worse.

## 4. Recommended actions
Check the terminals and connector, measure the sensor with a handheld thermometer, swap the sensor or move it to a spare channel. Priority 3 by default; priority 2 if the signal is part of a protective chain (for example a thermal trip), because the protection may be blind. Confirm that no protective function relies on the affected signal.

## 5. Data quality note
Do not use stuck or missing periods for trend analysis, OEE, or model training. Mark them as invalid.
