"""Checks against numbers stated in the papers. Run from analysis/: python -m tests.test_power"""
from lib import power as p

zero = float(p.piovesan(0))
assert abs(float(p.piovesan(1)) - 1) < 1e-9
assert abs(zero - 0.718) < 0.001
assert abs((1 - float(p.piovesan(0, pa_off=1)) / zero) - 0.34) < 0.005  # symbol: 34 %
assert abs((1 - p.CARRIER_OFF / zero) - 0.47) < 0.005                    # carrier: 47 %
assert abs((1 - p.DORMANT / zero) - 0.70) < 0.01                         # dormancy: 70 %
assert abs(float(p.earth(1, "Macro")) - 1344) < 1                        # paper: 1350 W

# Bjornson: baseband complexity at the ZF optimum (M=165, K=104, B=20 MHz) is 710 Gflops (Sec. VII-A).
# Removing the fixed terms of the formula (P_FIX + M P_BS + P_SYN) leaves P_CE + P_LP at the BS.
gflops = (float(p.bjornson(0, 0, m=165, k=104, b=20e6, ptx_w=0)) - 18 - 165 - 2) * 12.8
assert abs(gflops - 710) < 1
# Each term scales as in eq. (23)-(27): one W per antenna, 0.35 W per Gbit/s, PA efficiency 0.39
assert abs(float(p.bjornson(0, 1) - p.bjornson(0, 0)) - 0.35) < 1e-9
assert abs(float(p.bjornson(1, 0, ptx_w=39) - p.bjornson(0, 0, ptx_w=39)) - 100) < 1e-9
# EARTH Table 2: sleep state of a macro site is 6 x 75 W
assert abs(float(p.earth(0, "Macro", asleep=1)) - 450) < 1e-9
print("ok")
