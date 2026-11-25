"""Base-station power models. Piovesan works in units of the AAU peak power."""
import numpy as np

# Piovesan et al. 2022, fitted values (normalised), AAU with C=2 carriers, T=1 band, 64 chains.
P0, PBB, D_TRAN, D_PA, ETA, M_AV = 0.22, 0.16, 1.47e-3, 3.81e-3, 0.4, 64
P_TRAN = M_AV * D_TRAN
P_PA = M_AV * D_PA
# The paper does not list PTX. Normalisation to peak power (P=1 at full load) fixes its maximum.
PTX_MAX = ETA * (1 - P0 - PBB - P_TRAN - P_PA)

# Nominal peak in watt: Uitto macro site at saturation (1090 W) minus its 4G anchor (~160 W).
P_PEAK_W = 1090.0 - 160.0
ANCHOR_W_PER_MBPS = 1.0  # ASSUMPTION: extra 4G power (Uitto: 160 W idle -> 170 W at 10 Mbit/s)


def piovesan(load, m_ac=M_AV, pa_off=0.0):
    """AAU power while active. load: DL PRB load of the AAU, 0..1.
    pa_off: fraction of time the PAs are off (symbol shutdown).
    Each PA keeps its own maximum, so radiated power scales with m_ac."""
    load, pa_off = np.asarray(load, float), np.asarray(pa_off, float)
    return (P0 + PBB + P_TRAN + m_ac * D_PA * (1 - pa_off)
            + load * PTX_MAX * (m_ac / M_AV) / ETA)


# All carriers of the AAU off. With a shared MCPA, switching off one carrier of two leaves
# the PAs (and the single transceiver, T=1) on, and saves no static power.
CARRIER_OFF = P0 + PBB
DORMANT = P0


def earth(load, kind="RRH", asleep=0.0):
    """EARTH (Auer et al. 2011, Table 2), LTE site, watt. load = Pout/Pmax averaged over time.
    asleep: fraction of time without transmission, spent in the micro sleep state (Psleep)."""
    n, pmax, p0, dp, psleep = {"Macro": (6, 20.0, 130.0, 4.7, 75.0),
                               "RRH": (6, 20.0, 84.0, 2.8, 56.0)}[kind]
    f = np.asarray(asleep, float)
    return n * (p0 * (1 - f) + psleep * f + dp * pmax * np.asarray(load, float))


def bjornson(load, rate_gbps, m=64, k=10, b=60e6, ptx_w=PTX_MAX * P_PEAK_W):
    """Bjornson et al. 2015, BS-side terms, Table II, ZF; watt. Only DL data is simulated."""
    l_bs, u = 12.8e9, 1800.0
    p_tc = m * 1.0 + 2.0
    p_ce = b / u * 2 * m * k**2 / l_bs
    p_lp = (b * (1 - 2 * k / u) * 2 * m * k / l_bs
            + b / u * (k**3 / (3 * l_bs) + (3 * m * k**2 + m * k) / l_bs))
    return (np.asarray(load, float) * ptx_w / 0.39 + 18.0 + p_tc + p_ce + p_lp
            + np.asarray(rate_gbps, float) * (0.1 + 0.25))
