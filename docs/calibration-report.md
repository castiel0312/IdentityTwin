# Risk Engine Calibration Report

This report is produced by `scripts/run_calibration.py` from the committed synthetic dataset. Every number below is measured by replaying the synthetic identities through the shipped engine; nothing is estimated.

## Setup

- Synthetic seed: `20260921`
- Identities: 1284
- Split: identities are shuffled with the seed and split 60/40 into calibration and hold-out.
- Action level: a session is *flagged* when the evaluated trust level reaches `RESTRICTED` (step-up required). `DECOY` and `ISOLATED` are also flagged.
- Thresholds in use: restricted `30.0`, decoy `60.0`, isolated `90.0`.
- The contract weights were **not** tuned by this harness. The report measures the shipped configuration.
- Cohort intent: the `slow_and_low` cohort is benign (rare but perfectly legitimate low volume activity). The `slow_and_low` attack type lives inside the `compromised` cohort.

## Calibration split

- Identities: 770 (663 benign, 107 compromised)
- Sessions replayed: 5893
- Events replayed: 36933
- False positive rate (flagged benign sessions): 0.02% (1/4930)
- Detection rate (flagged compromised identities): 80.37% (86/107)
- Mean session score: 9.07, max session score: 100.00

| cohort | label | identities | sessions | flagged sessions | session rate | max score |
| --- | --- | --- | --- | --- | --- | --- |
| compromised | compromised | 107 | 963 | 86 | detection rate 80.37% | 100.00 |
| high_value | benign | 55 | 440 | 1 | false positive rate 0.23% | 32.00 |
| high_volume | benign | 72 | 720 | 0 | false positive rate 0.00% | 29.00 |
| new_sparse | benign | 66 | 198 | 0 | false positive rate 0.00% | 21.00 |
| regular | benign | 252 | 2016 | 0 | false positive rate 0.00% | 21.00 |
| shift_based | benign | 95 | 760 | 0 | false positive rate 0.00% | 21.00 |
| slow_and_low | benign | 47 | 188 | 0 | false positive rate 0.00% | 21.00 |
| traveling | benign | 76 | 608 | 0 | false positive rate 0.00% | 21.00 |

| attack type | identities | detected | detection rate | mean score | max score |
| --- | --- | --- | --- | --- | --- |
| canary_hit | 18 | 18 | 100.00% | 90.00 | 90.00 |
| device_takeover | 23 | 23 | 100.00% | 87.09 | 89.00 |
| payee_redirection | 19 | 19 | 100.00% | 84.95 | 89.00 |
| slow_and_low | 21 | 0 | 0.00% | 19.14 | 27.00 |
| velocity_burst | 26 | 26 | 100.00% | 100.00 | 100.00 |

## Holdout split

- Identities: 514 (441 benign, 73 compromised)
- Sessions replayed: 3823
- Events replayed: 23725
- False positive rate (flagged benign sessions): 0.00% (0/3166)
- Detection rate (flagged compromised identities): 79.45% (58/73)
- Mean session score: 9.14, max session score: 100.00

| cohort | label | identities | sessions | flagged sessions | session rate | max score |
| --- | --- | --- | --- | --- | --- | --- |
| compromised | compromised | 73 | 657 | 58 | detection rate 79.45% | 100.00 |
| high_value | benign | 45 | 360 | 0 | false positive rate 0.00% | 27.00 |
| high_volume | benign | 48 | 480 | 0 | false positive rate 0.00% | 29.00 |
| new_sparse | benign | 54 | 162 | 0 | false positive rate 0.00% | 21.00 |
| regular | benign | 148 | 1184 | 0 | false positive rate 0.00% | 21.00 |
| shift_based | benign | 55 | 440 | 0 | false positive rate 0.00% | 21.00 |
| slow_and_low | benign | 47 | 188 | 0 | false positive rate 0.00% | 21.00 |
| traveling | benign | 44 | 352 | 0 | false positive rate 0.00% | 21.00 |

| attack type | identities | detected | detection rate | mean score | max score |
| --- | --- | --- | --- | --- | --- |
| canary_hit | 18 | 18 | 100.00% | 90.00 | 90.00 |
| device_takeover | 13 | 13 | 100.00% | 88.15 | 89.00 |
| payee_redirection | 17 | 17 | 100.00% | 85.12 | 89.00 |
| slow_and_low | 15 | 0 | 0.00% | 18.93 | 27.00 |
| velocity_burst | 10 | 10 | 100.00% | 100.00 | 100.00 |

## Model decisions

- `LARGE_PAYOUT` is relative to the identity: a payout counts as large only when it exceeds the absolute threshold (`5000`) **and** is at least `3.0x` the average payout of that identity. A merchant whose payouts are naturally large is not permanently elevated, while a spike above its own norm still fires.
- `UNUSUAL_TIME` only applies to identities with a concentrated time of day profile (the busiest hour carries at least `25%` of the observed activity). For an identity that is active around the clock the hour carries no evidence, so the signal stays switched off.
- Device, location and payee observations are counted separately from the rest of the baseline. A context item joins the baseline after `2` observations, so a second phone or a second office is not flagged forever.
- Only an event whose sole finding is context newness and that keeps the session below the action threshold counts towards those observations. A hostile session therefore never confirms its own device, location or payee: the attacker stays unknown however often the attacker comes back.
- Client supplied risk flags are ignored. Every signal is derived server side from the twin baseline and the request facts.

## Known limitations

- `slow_and_low` fraud (a small payout to an unknown payee, from the identity's own device, location and hours) is **not detected**: it only carries the `NEW_PAYEE` signal (16 points) and stays below the restricted threshold of `30`. The engine has no velocity or cross-session correlation, so this pattern is reported as undetected rather than tuned away. The remaining attack types are detected in 100% of the replayed identities.
- The first session of every new identity carries the payee-add then pay sequence signal. It stays below the restricted threshold but it is a systematic noise source for cold identities.
- The amount baseline is fed by the established context only. An attacker who stays on the identity's own device and payee can slowly raise the average payout of an identity; the absolute threshold still fires for the first such payout.
- The hour-of-day model uses the merchant local time. A merchant that operates across several time zones is treated as one identity.
- Behavioural decay only removes transient per event evidence. Once a session holds session scoped evidence (new device, new location, unusual hour, canary) the decay stops and the session stays compromised until it ends.

## Reproduction

```bash
python scripts/generate_synthetic.py   # regenerate the fixture
python scripts/run_calibration.py        # regenerate this report
```
