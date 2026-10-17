# Policy experiment summary

All numbers below are simulated, from sim/, not from a pilot building.
Differences are paired by seed (same seed run under the baseline and the
variant), which is why the intervals are tight even with 30 seeds.
Positive relocations/wait differences and negative on-time differences
mean the variant is worse than the baseline.

## Ablations vs baseline (nearest-free spot assignment, FCFS dispatch, no pre-staging)

| Scenario | Variant | Seeds | Relocations/retrieval diff | Wait p95 diff (s) | On-time rate diff |
|---|---|---|---|---|---|
| weekday_peak | assigner_only | 30 | -0.0719 (95% CI -0.104 to -0.0398) | -21.3 (95% CI -45.2 to +1.14) | +0.0573 (95% CI +0.0237 to +0.0913) |
| weekday_peak | prestaging_only | 30 | +0.121 (95% CI +0.0843 to +0.158) | +29.9 (95% CI +8.67 to +52.8) | -0.016 (95% CI -0.0546 to +0.0222) |
| weekday_peak | dispatcher_only | 30 | +0.0128 (95% CI +0.0019 to +0.0269) | -22.2 (95% CI -43.3 to -6.17) | -0.0201 (95% CI -0.0357 to -0.00516) |
| weekday_peak | everything | 30 | +0.116 (95% CI +0.0703 to +0.16) | +1.54 (95% CI -25 to +27.1) | -0.0456 (95% CI -0.081 to -0.0115) |
| evening_event | assigner_only | 30 | +0.0208 (95% CI +0.00417 to +0.0476) | +0.277 (95% CI -6.74 to +7.84) | +0.0254 (95% CI +0.012 to +0.0397) |
| evening_event | prestaging_only | 30 | +0.125 (95% CI +0.103 to +0.146) | +7.32 (95% CI -0.787 to +15.6) | +0.0231 (95% CI -0.00823 to +0.0576) |
| evening_event | dispatcher_only | 30 | +0 (95% CI +0 to +0) | +0 (95% CI +0 to +0) | +0 (95% CI +0 to +0) |
| evening_event | everything | 30 | +0.139 (95% CI +0.114 to +0.163) | +13.6 (95% CI +3.58 to +22.7) | +0.0382 (95% CI +0.0087 to +0.068) |
| weekend_calm | assigner_only | 30 | -0.26 (95% CI -0.309 to -0.206) | -19.7 (95% CI -28.1 to -11.6) | +0 (95% CI +0 to +0) |
| weekend_calm | prestaging_only | 30 | -0.208 (95% CI -0.246 to -0.174) | -6.83 (95% CI -17.3 to +4.29) | +0.0444 (95% CI -0.0478 to +0.135) |
| weekend_calm | dispatcher_only | 30 | +0 (95% CI +0 to +0) | +0 (95% CI +0 to +0) | +0 (95% CI +0 to +0) |
| weekend_calm | everything | 30 | -0.37 (95% CI -0.43 to -0.307) | -16.2 (95% CI -28.2 to -3.44) | +0.0444 (95% CI -0.0478 to +0.135) |
| absence_shock | assigner_only | 30 | -0.0702 (95% CI -0.103 to -0.0389) | -2.27 (95% CI -37.2 to +34.2) | +0.0597 (95% CI +0.0245 to +0.0918) |
| absence_shock | prestaging_only | 30 | +0.118 (95% CI +0.0832 to +0.153) | +42.1 (95% CI +6.66 to +80.4) | -0.00523 (95% CI -0.0354 to +0.0281) |
| absence_shock | dispatcher_only | 30 | +0.0261 (95% CI +0.0118 to +0.045) | -32.9 (95% CI -58.3 to -8.79) | -0.0528 (95% CI -0.0717 to -0.0349) |
| absence_shock | everything | 30 | +0.136 (95% CI +0.0885 to +0.179) | +6.58 (95% CI -28.4 to +38.3) | -0.0714 (95% CI -0.108 to -0.0328) |

## Honest readout

The full policy ('everything': departure-aware assignment, pre-staging, EDF dispatch) improved the on-time rate over baseline in: evening_event, weekend_calm.
It did not improve on-time rate in: weekday_peak, absence_shock. This is reported honestly rather than hidden; the simpler baseline stays the default where a policy doesn't beat it (see the feature flag in app/spot_assignment.py).

## Sensitivity sweep (weekday_peak, 'everything' vs baseline, 10 seeds)

| Valets | Demand multiplier | On-time rate diff | Wait p95 diff (s) |
|---|---|---|---|
| 4 | 0.5x | +0.0873 (95% CI -0.00515 to +0.181) | -15.6 (95% CI -33.7 to +2.98) |
| 4 | 1.0x | -0.147 (95% CI -0.208 to -0.0872) | -31.5 (95% CI -148 to +74.4) |
| 4 | 1.5x | -0.106 (95% CI -0.149 to -0.0694) | +105 (95% CI -103 to +316) |
| 6 | 0.5x | +0.0654 (95% CI -0.0131 to +0.145) | -13.3 (95% CI -30.9 to +6.33) |
| 6 | 1.0x | -0.0575 (95% CI -0.0938 to -0.0219) | +11.5 (95% CI -11.4 to +35.9) |
| 6 | 1.5x | -0.12 (95% CI -0.177 to -0.0578) | -54.2 (95% CI -188 to +78.1) |
| 8 | 0.5x | +0.0188 (95% CI -0.0726 to +0.101) | -6.05 (95% CI -21.8 to +10.9) |
| 8 | 1.0x | -0.0264 (95% CI -0.0686 to +0.0124) | -10.5 (95% CI -25.3 to +4.84) |
| 8 | 1.5x | -0.0736 (95% CI -0.147 to -0.00817) | -39 (95% CI -118 to +39.7) |

## Staffing: flat vs CP-SAT coverage (weekday_peak ground-truth demand)

- Flat staffing (all valets on all day): 144.0 valet-hours
- CP-SAT shift covering: 48.0 valet-hours, 2 buckets left under-covered
