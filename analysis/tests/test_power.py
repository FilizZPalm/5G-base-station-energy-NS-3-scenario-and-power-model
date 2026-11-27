"""Check the power models of lib/power.py against numbers stated in the papers.

Each check compares a value computed by our code with the value printed in the paper; a failing check stops with a
message. Prints "ok" if all pass. Run from analysis/:  ../.venv/bin/python -m tests.test_power
"""
from lib import power


def check(name, value, expected, tolerance):
    assert abs(value - expected) < tolerance, f"{name}: got {value}, expected {expected} +- {tolerance}"


# --- Piovesan et al. 2022 -----------------------------------------------------------------------------------------
zero_load = float(power.piovesan(0))
check("Piovesan, full load = peak power", float(power.piovesan(1)), 1, 1e-9)
check("Piovesan, zero load", zero_load, 0.718, 0.001)
# savings at zero load stated in the paper
check("symbol shutdown saves 34%", 1 - float(power.piovesan(0, pa_off=1)) / zero_load, 0.34, 0.005)
check("carriers off save 47%", 1 - power.CARRIER_OFF / zero_load, 0.47, 0.005)
check("dormancy saves 70%", 1 - power.DORMANT / zero_load, 0.70, 0.01)

# --- EARTH, Auer et al. 2011 --------------------------------------------------------------------------------------
check("EARTH macro site at full load (paper: 1350 W)", float(power.earth(1, "Macro")), 1344, 1)
check("EARTH macro site asleep, 6 x 75 W (Table 2)", float(power.earth(0, "Macro", asleep=1)), 450, 1e-9)

# --- Bjornson et al. 2015 -----------------------------------------------------------------------------------------
# Baseband complexity at the zero-forcing optimum (M=165, K=104, B=20 MHz) is 710 Gflops (Sec. VII-A). Removing the
# fixed terms of the formula (P_FIX + M P_BS + P_SYN = 18 + 165 + 2 W) leaves channel estimation and precoding, in W;
# times 12.8 Gflops/W gives Gflops.
gflops = (float(power.bjornson(0, 0, m=165, k=104, b=20e6, ptx_w=0)) - 18 - 165 - 2) * 12.8
check("Bjornson, 710 Gflops at the optimum", gflops, 710, 1)
# each term scales as in eq. (23)-(27): 0.35 W per Gbit/s, PA efficiency 0.39 (39 W radiated cost 100 W)
check("Bjornson, 0.35 W per Gbit/s", float(power.bjornson(0, 1) - power.bjornson(0, 0)), 0.35, 1e-9)
check("Bjornson, PA efficiency 0.39", float(power.bjornson(1, 0, ptx_w=39) - power.bjornson(0, 0, ptx_w=39)), 100, 1e-9)

print("ok")
