# MNT-102 Capper cooling and thermal protection

*Fictional example document for the Plant Ops Copilot demo.*

## 1. Scope
Applies to the capping head and torque unit cooling of the capper (CAPPER-01).

## 2. Temperature limits
Normal operating temperature is 48 to 56 degC. The alert limit is 62 degC. The thermal protection trips at 68 degC and locks the machine for a 10 minute cool-down.

## 3. Cooling fan failure signature
When the cooling fan or its contactor fails, the temperature rises exponentially with a time constant of about 40 minutes toward roughly 76 degC. The thermal protection then trips, the machine cools down, and the pattern repeats about every 25 minutes. Motor current and rejects rise slightly because cap torque becomes less consistent.

## 4. Other causes to rule out
A clogged air filter gives a slower, partial rise. Blocked air flow or a closed cabinet door behaves similarly. High ambient temperature would show up on several machines at the same time, so check the other machines. Degraded lubricant gives a temperature rise together with rising vibration.

## 5. Recommended actions
Do not keep resetting the thermal trip. Two or more trips within one hour is a priority 1 event. Check that the fan rotates and that its contactor pulls in. Clean the filter. Replace the 24 V fan if it is faulty. Verify the temperature stays below 62 degC for 15 minutes before releasing the machine to production.
