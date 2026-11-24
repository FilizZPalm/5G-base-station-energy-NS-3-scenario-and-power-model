"""Checks against numbers stated in the papers. Run: python test_power.py"""
import power as p

zero = float(p.piovesan(0))
assert abs(float(p.piovesan(1)) - 1) < 1e-9
assert abs(zero - 0.718) < 0.001
assert abs((1 - float(p.piovesan(0, pa_off=1)) / zero) - 0.34) < 0.005  # symbol: 34 %
assert abs((1 - p.CARRIER_OFF / zero) - 0.47) < 0.005                    # carrier: 47 %
assert abs((1 - p.DORMANT / zero) - 0.70) < 0.01                         # dormancy: 70 %
assert abs(float(p.earth(1, "Macro")) - 1344) < 1                        # paper: 1350 W
print("ok")
