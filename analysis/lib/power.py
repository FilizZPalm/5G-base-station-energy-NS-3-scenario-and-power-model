"""Power models of a 5G base station: how many watts for a given traffic.

Four models are here:
  piovesan  Piovesan et al. 2022, the main model of the study (power of the active antenna unit, AAU)
  earth     EARTH project, Auer et al. 2011, an older LTE model, for comparison (step 5)
  bjornson  Bjornson et al. 2015, a massive-MIMO model, for comparison (step 5)
  tgpp_*    3GPP TR 38.864, the model 3GPP uses for energy-saving studies (step 10)

Piovesan works in units of the AAU peak power (1 = full load, all 64 chains on); multiply by P_PEAK_W for watt.
"""
import numpy as np

# --- Piovesan et al. 2022 -----------------------------------------------------------------------------------------
# Fitted values, normalised to the peak power, for an AAU with C=2 carriers, T=1 band and 64 transceiver chains.
P0 = 0.22          # static power, always there while the AAU is on
PBB = 0.16         # baseband processing
D_TRAN = 1.47e-3   # one transceiver chain
D_PA = 3.81e-3     # one power amplifier (PA), while it is on
ETA = 0.4          # PA efficiency: radiated power / power drawn
M_AV = 64          # chains available
P_TRAN = M_AV * D_TRAN   # all transceivers
P_PA = M_AV * D_PA       # all PAs
# The paper does not give the transmitted power. Normalising to 1 at full load fixes its maximum:
PTX_MAX = ETA * (1 - P0 - PBB - P_TRAN - P_PA)

# Peak power in watt: a macro site at saturation (Uitto, 1090 W) minus its 4G anchor (about 160 W).
P_PEAK_W = 1090.0 - 160.0
ANCHOR_W_PER_MBPS = 1.0  # ASSUMPTION: extra 4G anchor power per Mbit/s (Uitto: 160 W idle -> 170 W at 10 Mbit/s)


def piovesan(load, m_ac=M_AV, pa_off=0.0):
    """AAU power while it is active, in units of the peak power.

    load    downlink resource-block load of the AAU, 0..1 (how much of the band carries data)
    m_ac    active chains, 16..64 (channel shutdown switches the others off)
    pa_off  share of the time the PAs are off (symbol shutdown), 0..1

    P = P0 + PBB + all transceivers + active PAs while on + transmitted power / efficiency.
    Each PA keeps its own maximum output, so the radiated power scales with the active chains.
    """
    load, pa_off = np.asarray(load, float), np.asarray(pa_off, float)
    return (P0 + PBB + P_TRAN + m_ac * D_PA * (1 - pa_off)
            + load * PTX_MAX * (m_ac / M_AV) / ETA)


# Deeper states of the whole AAU, used only with the power formula (no simulated wake-up):
# all carriers off. With one PA shared by both carriers, switching off one carrier of two leaves the PAs and the
# single transceiver on and saves no static power, so only "all carriers off" is meaningful.
CARRIER_OFF = P0 + PBB
DORMANT = P0       # deep dormancy: only the static power remains


# --- EARTH, Auer et al. 2011 (Table 2) -----------------------------------------------------------------------------
def earth(load, kind="RRH", asleep=0.0):
    """Power of an LTE site in watt (6 PAs of 20 W).

    load    output power / maximum, averaged over time
    kind    "Macro" (classic site) or "RRH" (remote radio head)
    asleep  share of the time without transmission, spent in the micro-sleep state
    """
    n_pa, p_max, p_zero, slope, p_sleep = {"Macro": (6, 20.0, 130.0, 4.7, 75.0),
                                           "RRH": (6, 20.0, 84.0, 2.8, 56.0)}[kind]
    f = np.asarray(asleep, float)
    return n_pa * (p_zero * (1 - f) + p_sleep * f + slope * p_max * np.asarray(load, float))


# --- Bjornson et al. 2015 (Table II, zero-forcing precoding) -------------------------------------------------------
def bjornson(load, rate_gbps, m=64, k=10, b=60e6, ptx_w=PTX_MAX * P_PEAK_W):
    """Base-station side of the massive-MIMO model, in watt. Only downlink data is simulated.

    load       transmitted power / maximum
    rate_gbps  traffic carried [Gbit/s] (coding and backhaul cost per bit)
    m, k, b    antennas, users served together, bandwidth [Hz]
    """
    l_bs = 12.8e9     # operations per joule of the processors
    u = 1800.0        # samples per coherence block
    p_tc = m * 1.0 + 2.0                                                  # transceiver chains + oscillator
    p_ce = b / u * 2 * m * k**2 / l_bs                                    # channel estimation
    p_lp = (b * (1 - 2 * k / u) * 2 * m * k / l_bs                        # linear processing (precoding)
            + b / u * (k**3 / (3 * l_bs) + (3 * m * k**2 + m * k) / l_bs))
    return (np.asarray(load, float) * ptx_w / 0.39 + 18.0 + p_tc + p_ce + p_lp
            + np.asarray(rate_gbps, float) * (0.1 + 0.25))


# --- 3GPP TR 38.864 V18.1.0 (2023), clause 5.1 ---------------------------------------------------------------------
# Powers are relative (deep sleep = 1) for the reference base station "Set 1": TDD in FR1, 100 MHz, 30 kHz, 64
# transmit radio units (RUs), 55 dBm. The report gives two alternative sets of values, Category 1 and 2, and does not
# say which applies to which equipment. Keys:
#   deep, light, micro   power in the three sleep states (Table 5.1-3)
#   dl, ul               power in a full downlink symbol and in an uplink symbol
#   t_light, t_deep      total transition time into and out of the sleep state [ms] (Table 5.1-4)
#   e_light, e_deep      extra energy of one transition [relative power x ms] (Table 5.1-5)
TGPP = {1: dict(deep=1, light=25, micro=55, dl=280, ul=110, t_light=6, t_deep=50, e_light=90, e_deep=1000),
        2: dict(deep=1, light=2.1, micro=5.5, dl=32, ul=6.5, t_light=640, t_deep=10000, e_light=1088, e_deep=17000)}
TGPP_A = 0.4          # share of the dynamic downlink power that scales with the active RUs
TGPP_RB_REF = 273     # resource blocks of the 100 MHz reference carrier at 30 kHz
TGPP_EXTRA_CC = 0.7   # each additional contiguous carrier costs 0.7 of the first


def tgpp_dl_symbol(rb, active_ru=1.0, cat=1):
    """Power of one downlink symbol of one carrier with rb resource blocks in use.

    P = micro + active_ru * A * (dl - micro) + rb / 273 * (1 - A) * (dl - micro):
    part of the power grows with the active radio units, part with the resource blocks in use.
    """
    p = TGPP[cat]
    dyn = p["dl"] - p["micro"]
    return p["micro"] + active_ru * TGPP_A * dyn + np.asarray(rb, float) / TGPP_RB_REF * (1 - TGPP_A) * dyn


def tgpp_ul_symbol(active_ru=1.0, cat=1):
    """Power of one uplink symbol of one carrier: micro + active_ru * (ul - micro)."""
    p = TGPP[cat]
    return p["micro"] + active_ru * (p["ul"] - p["micro"])
