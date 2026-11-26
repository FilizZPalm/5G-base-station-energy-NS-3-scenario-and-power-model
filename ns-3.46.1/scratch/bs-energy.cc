// Downlink scenario for base-station energy evaluation (5G-LENA).
//
// One AAU per site with two contiguous n78 carriers; UEs are statically split between
// the carriers through their QCI. Traffic profiles over UDP: night (few UEs, rare Poisson bursts),
// day (all UEs, Poisson bursts), peak (video UEs, Poisson bursts on the others). Video is sent as
// DASH-like segments (paced on-off) or as CBR. The program
// exports raw per-slot occupancy of every carrier of cell 0 (the AAU under study) and
// per-flow QoS of its UEs. No power model here: energy is computed in analysis/.
#include "ns3/antenna-module.h"
#include "ns3/applications-module.h"
#include "ns3/core-module.h"
#include "ns3/flow-monitor-module.h"
#include "ns3/internet-module.h"
#include "ns3/mobility-module.h"
#include "ns3/network-module.h"
#include "ns3/nr-module.h"
#include "ns3/spectrum-module.h"

#include <algorithm>
#include <array>
#include <fstream>
#include <functional>

using namespace ns3;

NS_LOG_COMPONENT_DEFINE("BsEnergy");

static std::ofstream g_slots;
static Time g_warmup;

static void
SlotData(uint32_t carrier,
         const SfnSf& sfn,
         uint32_t ues,
         uint32_t usedReg,
         uint32_t usedSym,
         uint32_t availRb,
         uint32_t availSym,
         uint16_t,
         uint16_t)
{
    if (Simulator::Now() < g_warmup)
    {
        return;
    }
    g_slots << sfn.Normalize() << ',' << carrier << ',' << ues << ',' << usedReg << ',' << usedSym
            << ',' << availRb << ',' << availSym << '\n';
}

/// Downlink occupancy of a site (both carriers), sums over the DL slots.
struct CellLoad
{
    uint64_t slots{0}, usedReg{0}, availReg{0}, usedSym{0}, availSym{0};
};

static std::vector<CellLoad> g_cells;

static void
CellData(uint32_t cell,
         const SfnSf&,
         uint32_t,
         uint32_t usedReg,
         uint32_t usedSym,
         uint32_t availRb,
         uint32_t availSym,
         uint16_t,
         uint16_t)
{
    if (Simulator::Now() < g_warmup)
    {
        return;
    }
    auto& c = g_cells[cell];
    c.slots++;
    c.usedReg += usedReg;
    c.availReg += availRb * availSym;
    c.usedSym += usedSym;
    c.availSym += availSym;
}

/// Radio quality of the transport blocks received by a UE; sums weighted by resources (RB x symbols).
struct RxStats
{
    uint64_t tbs{0}, retx{0}, corrupt{0}, okBytes{0};
    double res{0}, sinrDb{0}, mcs{0}, rank{0}, syms{0}, tbler{0};
    std::array<uint64_t, 2> last{UINT64_MAX, UINT64_MAX}; // per carrier
};

static std::map<uint32_t, RxStats> g_rx;
static std::ofstream g_tb; // one line per transport block, only with --tbTrace

static void
RxTb(uint32_t ue, uint32_t carrier, RxPacketTraceParams p)
{
    if (Simulator::Now() < g_warmup)
    {
        return;
    }
    auto& s = g_rx[ue];
    // The trace fires once per packet of the block: count each block once.
    const uint64_t id = ((uint64_t(p.m_frameNum) * 10 + p.m_subframeNum) * 16 + p.m_slotNum) * 16 +
                        p.m_symStart;
    if (s.last[carrier] == id)
    {
        return;
    }
    s.last[carrier] = id;
    const double w = double(p.m_rbAssignedNum) * p.m_numSym;
    s.tbs++;
    s.retx += p.m_rv > 0;
    s.corrupt += p.m_corrupt;
    s.okBytes += p.m_corrupt ? 0 : p.m_tbSize;
    s.res += w;
    s.sinrDb += w * 10 * log10(p.m_sinr);
    s.mcs += w * p.m_mcs;
    s.rank += w * p.m_rank;
    s.syms += p.m_numSym;
    s.tbler += p.m_tbler;
    if (g_tb.is_open())
    {
        g_tb << (id >> 4) << ',' << ue << ',' << carrier << ',' << +p.m_symStart << ','
             << +p.m_numSym << ',' << p.m_rbAssignedNum << ',' << p.m_tbSize << ',' << +p.m_mcs
             << ',' << +p.m_rank << ',' << +p.m_rv << ',' << 10 * log10(p.m_sinr) << ','
             << 10 * log10(p.m_sinrMin) << ',' << p.m_tbler << ',' << p.m_corrupt << ','
             << +p.m_cqi << '\n';
    }
}

/// Poisson arrivals of fixed-size bursts; each burst is sent as back-to-back packets.
class BurstSource : public SimpleRefCount<BurstSource>
{
  public:
    BurstSource(Ptr<Socket> s, double rateBps, uint32_t burstBytes, Time stop, int64_t stream)
        : m_socket(s),
          m_burst(burstBytes),
          m_stop(stop)
    {
        m_gap = CreateObject<ExponentialRandomVariable>();
        m_gap->SetAttribute("Mean", DoubleValue(burstBytes * 8.0 / rateBps));
        m_gap->SetStream(stream);
    }

    void ScheduleNext()
    {
        Time t = Seconds(m_gap->GetValue());
        if (Simulator::Now() + t < m_stop)
        {
            Simulator::Schedule(t, &BurstSource::Fire, this);
        }
    }

  private:
    void Fire()
    {
        for (uint32_t left = m_burst; left > 0;)
        {
            uint32_t n = std::min<uint32_t>(left, 1400);
            m_socket->Send(Create<Packet>(n));
            left -= n;
        }
        ScheduleNext();
    }

    Ptr<Socket> m_socket;
    uint32_t m_burst;
    Time m_stop;
    Ptr<ExponentialRandomVariable> m_gap;
};

/// Constant bit rate video: evenly spaced packets, as in the CBR streams of Uitto et al.
class CbrSource : public SimpleRefCount<CbrSource>
{
  public:
    CbrSource(Ptr<Socket> s, double rateBps, Time stop)
        : m_socket(s),
          m_gap(Seconds(1400 * 8.0 / rateBps)),
          m_stop(stop)
    {
    }

    void Fire()
    {
        if (Simulator::Now() < m_stop)
        {
            m_socket->Send(Create<Packet>(1400));
            Simulator::Schedule(m_gap, &CbrSource::Fire, this);
        }
    }

  private:
    Ptr<Socket> m_socket;
    Time m_gap;
    Time m_stop;
};

/// Segmented (DASH-like) video: every period one segment is sent as packets paced at the
/// server rate, then the source is silent. It starts in steady state with a given phase.
class SegmentSource : public SimpleRefCount<SegmentSource>
{
  public:
    static constexpr uint32_t PKT = 1400;

    struct Segment
    {
        Time start;
        uint32_t sent{0};
        uint32_t rx{0};
        Time lastRx;
    };

    SegmentSource(Ptr<Socket> s, double rateBps, double periodS, double paceBps, Time stop)
        : m_socket(s),
          m_n(std::ceil(rateBps * periodS / 8 / PKT)),
          m_period(Seconds(periodS)),
          m_gap(Seconds(PKT * 8 / paceBps)),
          m_stop(stop)
    {
        NS_ABORT_MSG_IF(m_gap * m_n > m_period, "videoPaceMbps is below the video rate");
    }

    /// First segment starts phase - period after now: only its remaining packets are sent.
    void Start(Time phase)
    {
        BeginSegment(Simulator::Now() + phase - m_period);
    }

    void Received(Ptr<const Packet> p, const Address&)
    {
        SeqTsHeader h;
        p->PeekHeader(h);
        auto& seg = m_segments[h.GetSeq() / m_n];
        seg.rx++;
        seg.lastRx = Simulator::Now();
    }

    uint32_t PacketsPerSegment() const
    {
        return m_n;
    }

    const std::vector<Segment>& Segments() const
    {
        return m_segments;
    }

  private:
    void BeginSegment(Time start)
    {
        m_segments.emplace_back();
        m_segments.back().start = start;
        // Packets that would have been sent before now are skipped (first segment only).
        uint32_t first = 0;
        while (first < m_n && start + m_gap * first < Simulator::Now())
        {
            first++;
        }
        if (first < m_n)
        {
            Simulator::Schedule(start + m_gap * first - Simulator::Now(),
                                &SegmentSource::Send,
                                this,
                                first);
        }
        if (start + m_period < m_stop)
        {
            Simulator::Schedule(start + m_period - Simulator::Now(),
                                &SegmentSource::BeginSegment,
                                this,
                                start + m_period);
        }
    }

    void Send(uint32_t i)
    {
        if (Simulator::Now() >= m_stop)
        {
            return;
        }
        SeqTsHeader h;
        h.SetSeq((m_segments.size() - 1) * m_n + i);
        auto p = Create<Packet>(PKT - h.GetSerializedSize());
        p->AddHeader(h);
        m_socket->Send(p);
        m_segments.back().sent++;
        if (i + 1 < m_n)
        {
            Simulator::Schedule(m_gap, &SegmentSource::Send, this, i + 1);
        }
    }

    Ptr<Socket> m_socket;
    uint32_t m_n;
    Time m_period;
    Time m_gap;
    Time m_stop;
    std::vector<Segment> m_segments;
};

/// Sleep state of the AAU of cell 0, shared by the schedulers of its carriers (one MCPA).
/// After an idle timer it sleeps; down and up transitions take Tw each; traffic or a planned SSB
/// wakes it up. Nothing is scheduled while it is not awake.
class SleepController : public SimpleRefCount<SleepController>
{
  public:
    enum State
    {
        AWAKE,
        DOWN,
        SLEEP,
        UP
    };

    SleepController(double twMs, double ssbMs, double timerTw)
        : m_tw(std::lround(twMs / 0.5)),
          m_ssb(std::lround(ssbMs / 0.5)),
          m_timer(std::lround(timerTw * twMs / 0.5))
    {
    }

    /// Called at every slot boundary, starting from slot 0 at time 0.
    void Tick()
    {
        const int64_t slot = m_slot++;
        const int64_t toSsb = m_ssb > 0 ? (m_ssb - slot % m_ssb) % m_ssb : INT64_MAX / 4;
        if (m_enabled && Simulator::Now() < m_stop)
        {
            m_count[m_state]++;
        }
        if ((m_state == DOWN || m_state == UP) && --m_left <= 0)
        {
            m_state = m_state == DOWN ? SLEEP : AWAKE;
            m_lastActivity = slot;
            if (m_state == AWAKE)
            {
                Release();
            }
        }
        else if (m_state == SLEEP && (m_waiting || toSsb <= m_tw))
        {
            m_wakes += m_waiting;
            Go(UP);
        }
        else if (m_state == AWAKE && m_enabled && !Busy() && slot - m_lastActivity > m_timer &&
                 toSsb > 2 * m_tw + 1)
        {
            Go(DOWN);
        }
        // Keeps running during the drain, otherwise held data would never be released.
        Simulator::Schedule(MicroSeconds(500), &SleepController::Tick, this);
    }

    void Start(Time enable, Time stop)
    {
        m_stop = stop;
        Simulator::Schedule(enable, &SleepController::Enable, this);
        Simulator::Schedule(Seconds(0), &SleepController::Tick, this);
    }

    bool Awake() const
    {
        return m_state == AWAKE;
    }

    void Activity()
    {
        m_lastActivity = m_slot;
    }

    /// Counts DL data or feedback while not awake: must stay at zero.
    void CheckAwake()
    {
        m_violations += !Awake();
    }

    void TrafficWaiting()
    {
        m_waiting = true;
    }

    void OnRelease(std::function<void()> cb)
    {
        m_release.push_back(cb);
    }

    /// Registers a check for HARQ feedback still expected by a scheduler.
    void OnPending(std::function<bool()> f)
    {
        m_pending.push_back(f);
    }

    void Print(std::ostream& os) const
    {
        os << "awake,down,sleep,up,wakes_by_traffic,violations\n"
           << m_count[AWAKE] << ',' << m_count[DOWN] << ',' << m_count[SLEEP] << ',' << m_count[UP]
           << ',' << m_wakes << ',' << m_violations << '\n';
    }

  private:
    bool Busy() const
    {
        return std::any_of(m_pending.begin(), m_pending.end(), [](auto& f) { return f(); });
    }

    void Enable()
    {
        m_enabled = true;
    }

    void Go(State s)
    {
        m_state = s;
        m_left = m_tw;
    }

    void Release()
    {
        m_waiting = false;
        for (auto& cb : m_release)
        {
            cb();
        }
    }

    int64_t m_tw;
    int64_t m_ssb;
    int64_t m_timer;
    State m_state{AWAKE};
    int64_t m_left{0};
    int64_t m_slot{0};
    int64_t m_lastActivity{0};
    bool m_waiting{false};
    bool m_enabled{false};
    Time m_stop;
    uint64_t m_count[4]{};
    uint64_t m_wakes{0};
    uint64_t m_violations{0};
    std::vector<std::function<void()>> m_release;
    std::vector<std::function<bool()>> m_pending;
};

static Ptr<SleepController> g_sleep;

/// OFDMA PF scheduler that learns about new data only when the AAU is awake.
class SleepyScheduler : public NrMacSchedulerOfdmaPF
{
  public:
    static TypeId GetTypeId()
    {
        static TypeId tid = TypeId("ns3::SleepyScheduler")
                                .SetParent<NrMacSchedulerOfdmaPF>()
                                .AddConstructor<SleepyScheduler>();
        return tid;
    }

    SleepyScheduler()
    {
        g_sleep->OnRelease([this]() { Flush(); });
        g_sleep->OnPending([this]() { return FeedbackPending(); });
    }

    void DoSchedDlRlcBufferReq(
        const NrMacSchedSapProvider::SchedDlRlcBufferReqParameters& params) override
    {
        const bool data = params.m_rlcTransmissionQueueSize + params.m_rlcRetransmissionQueueSize +
                              params.m_rlcStatusPduSize >
                          0;
        if (g_sleep->Awake())
        {
            if (data)
            {
                g_sleep->Activity();
            }
            NrMacSchedulerOfdmaPF::DoSchedDlRlcBufferReq(params);
            return;
        }
        // The latest report replaces the earlier ones: it carries the whole queue size.
        m_held[{params.m_rnti, params.m_logicalChannelIdentity}] = params;
        if (data)
        {
            g_sleep->TrafficWaiting();
        }
    }

    void DoSchedDlTriggerReq(
        const NrMacSchedSapProvider::SchedDlTriggerReqParameters& params) override
    {
        for (const auto& h : params.m_dlHarqInfoList)
        {
            Feedback(h);
        }
        NrMacSchedulerOfdmaPF::DoSchedDlTriggerReq(params);
    }

  protected:
    std::shared_ptr<DciInfoElementTdma> CreateDlDci(
        PointInFTPlane* spoint,
        const std::shared_ptr<NrMacSchedulerUeInfo>& ueInfo,
        uint32_t maxSym) const override
    {
        auto dci = NrMacSchedulerOfdmaPF::CreateDlDci(spoint, ueInfo, maxSym);
        if (dci)
        {
            g_sleep->CheckAwake();
            m_waiting.push_back({Simulator::Now(), dci});
            g_sleep->Activity();
        }
        return dci;
    }

  private:
    /// Data transmission waiting for its feedback; last is the time of the latest transmission.
    struct Waiting
    {
        Time last;
        std::shared_ptr<DciInfoElementTdma> dci;
    };

    void Feedback(const DlHarqInfo& h)
    {
        g_sleep->CheckAwake();
        g_sleep->Activity();
        auto it = std::find_if(m_waiting.begin(), m_waiting.end(), [&h](const Waiting& w) {
            return w.dci->m_rnti == h.m_rnti && w.dci->m_harqProcess == h.m_harqProcessId;
        });
        if (it == m_waiting.end())
        {
            return;
        }
        if (h.IsReceivedOk() || h.m_numRetx >= 3)
        {
            m_waiting.erase(it);
        }
        else
        {
            it->last = Simulator::Now(); // a retransmission follows
        }
    }

    bool FeedbackPending()
    {
        // Some allocations never get any feedback: do not wait for them longer than FEEDBACK.
        std::erase_if(m_waiting, [](const Waiting& w) { return Simulator::Now() - w.last > FEEDBACK; });
        return !m_waiting.empty();
    }

    void Flush()
    {
        for (auto& [key, params] : m_held)
        {
            NrMacSchedulerOfdmaPF::DoSchedDlRlcBufferReq(params);
        }
        m_held.clear();
        g_sleep->Activity();
    }

    static inline const Time FEEDBACK = MilliSeconds(6); // seen within 5 ms
    mutable std::vector<Waiting> m_waiting;
    std::map<std::pair<uint16_t, uint8_t>, NrMacSchedSapProvider::SchedDlRlcBufferReqParameters>
        m_held;
};

NS_OBJECT_ENSURE_REGISTERED(SleepyScheduler);

/// Outer loop link adaptation, not in 5G-LENA: a per-UE MCS backoff learnt from the HARQ feedback
/// of first transmissions. NACK: +step; ACK: -step * target / (1 - target). The backoff settles where
/// the first-transmission BLER equals the target; it may go negative (MCS above the CQI choice).
struct OllaConfig
{
    double step{0}; // MCS steps per NACK, 0: off
    double target{0.1};
};

static OllaConfig g_olla;

template <class Base>
class Olla : public Base
{
  public:
    void DoSchedDlCqiInfoReq(
        const NrMacSchedSapProvider::SchedDlCqiInfoReqParameters& params) override
    {
        Base::DoSchedDlCqiInfoReq(params); // sets the MCS of each UE from its CQI
        const int maxMcs = static_cast<int>(this->GetDlAmc()->GetMaxMcs());
        for (const auto& c : params.m_cqiList)
        {
            auto ue = m_ues[c.m_rnti].lock();
            if (ue)
            {
                const int mcs = ue->m_dlMcs - static_cast<int>(std::lround(m_backoff[c.m_rnti]));
                ue->m_dlMcs = static_cast<uint8_t>(std::clamp(mcs, 0, maxMcs));
            }
        }
    }

    void DoSchedDlTriggerReq(
        const NrMacSchedSapProvider::SchedDlTriggerReqParameters& params) override
    {
        for (const auto& h : params.m_dlHarqInfoList)
        {
            if (h.m_numRetx == 0) // redundancy version 0: a first transmission
            {
                auto& b = m_backoff[h.m_rnti];
                b += h.IsReceivedOk() ? -g_olla.step * g_olla.target / (1 - g_olla.target)
                                      : g_olla.step;
                b = std::clamp(b, -MAX_BACKOFF, MAX_BACKOFF);
            }
        }
        Base::DoSchedDlTriggerReq(params);
    }

  protected:
    std::shared_ptr<NrMacSchedulerUeInfo> CreateUeRepresentation(
        const NrMacCschedSapProvider::CschedUeConfigReqParameters& params) const override
    {
        auto ue = Base::CreateUeRepresentation(params);
        m_ues[params.m_rnti] = ue;
        return ue;
    }

  private:
    static constexpr double MAX_BACKOFF = 15; // MCS steps
    mutable std::map<uint16_t, std::weak_ptr<NrMacSchedulerUeInfo>> m_ues;
    std::map<uint16_t, double> m_backoff; // MCS steps, per UE
};

class OllaOfdma : public Olla<NrMacSchedulerOfdmaPF>
{
  public:
    static TypeId GetTypeId()
    {
        static TypeId tid = TypeId("ns3::OllaOfdma")
                                .SetParent<NrMacSchedulerOfdmaPF>()
                                .AddConstructor<OllaOfdma>();
        return tid;
    }
};

class OllaTdma : public Olla<NrMacSchedulerTdmaPF>
{
  public:
    static TypeId GetTypeId()
    {
        static TypeId tid = TypeId("ns3::OllaTdma")
                                .SetParent<NrMacSchedulerTdmaPF>()
                                .AddConstructor<OllaTdma>();
        return tid;
    }
};

NS_OBJECT_ENSURE_REGISTERED(OllaOfdma);
NS_OBJECT_ENSURE_REGISTERED(OllaTdma);

int
main(int argc, char* argv[])
{
    std::string profile = "day";
    double loadMbps = -1;    // offered DL burst load per cell, <0: profile default
    int activeUes = -1;      // UEs with traffic per site, <0: profile default
    uint32_t antennas = 64;  // active RF chains: 64, 32 or 16 (channel shutdown)
    uint32_t neighborAntennas = 64; // chains of the other sites
    bool suMimo = true;             // 2 streams per UE over dual-polarized arrays, same element count
    uint32_t nGnb = 3;
    uint32_t uesPerGnb = 10;
    double radius = 250;     // m
    double peakTxW = 104.9;  // AAU radiated power with 64 chains, both carriers at full load
    double bwPerCarrier = 30e6;
    uint32_t burstBytes = 25000;
    std::string videoModel = "segments";
    double segmentS = 2.0;        // ASSUMPTION: segment length
    double videoPaceMbps = 100.0; // ASSUMPTION: server rate while a segment is sent
    double drain = 0.05;
    std::string association = "best";
    std::string scheduler = "ofdma"; // PF in both cases
    std::string neighborScheduler; // empty: as scheduler
    bool tbTrace = false;
    double sleepTwMs = 0;    // wake-up (and fall-asleep) time of the sleep mode, 0: no sleep
    double sleepSsbMs = 20;  // SSB period, 0: no SSB
    double sleepTimerTw = 2; // idle time before sleeping, in units of Tw
    bool sharedShadowing = true; // same LOS state and shadowing on both carriers
    double warmup = 0.3;
    double duration = 1.0;
    uint32_t run = 1;
    std::string out = "run";

    CommandLine cmd(__FILE__);
    cmd.AddValue("profile", "night, day or peak", profile);
    cmd.AddValue("loadMbps", "Offered DL burst load per cell [Mbit/s]", loadMbps);
    cmd.AddValue("activeUes", "UEs with traffic per site", activeUes);
    cmd.AddValue("antennas", "Active RF chains of cell 0 (64, 48, 32, 24, 16)", antennas);
    cmd.AddValue("neighborAntennas", "Active RF chains of the other sites", neighborAntennas);
    cmd.AddValue("suMimo", "Enable SU-MIMO (2 streams, dual polarization)", suMimo);
    cmd.AddValue("nGnb", "Number of sites", nGnb);
    cmd.AddValue("uesPerGnb", "UEs per site", uesPerGnb);
    cmd.AddValue("radius", "Cell radius [m]", radius);
    cmd.AddValue("peakTxW", "Total AAU TX power at 64 chains [W]", peakTxW);
    cmd.AddValue("bwPerCarrier", "Bandwidth per carrier [Hz]", bwPerCarrier);
    cmd.AddValue("burstBytes", "Burst size [byte]", burstBytes);
    cmd.AddValue("video", "Video model: segments or cbr", videoModel);
    cmd.AddValue("segmentS", "Video segment length [s]", segmentS);
    cmd.AddValue("videoPaceMbps", "Server rate while sending a segment [Mbit/s]", videoPaceMbps);
    cmd.AddValue("association",
                 "best: UEs are redrawn until their own site is the strongest; geometric: no check",
                 association);
    cmd.AddValue("sharedShadowing",
                 "Both carriers share LOS state and shadowing",
                 sharedShadowing);
    cmd.AddValue("sleepTwMs", "Wake-up time of the sleep mode of cell 0 [ms], 0: off", sleepTwMs);
    cmd.AddValue("sleepSsbMs", "SSB period [ms], 0: none", sleepSsbMs);
    cmd.AddValue("sleepTimerTw", "Idle time before sleeping [Tw]", sleepTimerTw);
    cmd.AddValue("ollaStep",
                 "Outer loop link adaptation: MCS steps added per NACK, all sites, 0: off",
                 g_olla.step);
    cmd.AddValue("ollaTarget", "Outer loop link adaptation: target first-transmission BLER", g_olla.target);
    cmd.AddValue("scheduler", "ofdma or tdma (proportional fair)", scheduler);
    cmd.AddValue("tbTrace", "Write every transport block received in cell 0", tbTrace);
    cmd.AddValue("neighborScheduler",
                 "ofdma or tdma in the other sites, empty: as scheduler",
                 neighborScheduler);
    cmd.AddValue("drain", "Extra time after the last transmission [s]", drain);
    cmd.AddValue("warmup", "Discarded initial time [s]", warmup);
    cmd.AddValue("duration", "Measured time [s]", duration);
    cmd.AddValue("run", "RNG run", run);
    cmd.AddValue("out", "Output file prefix", out);
    cmd.Parse(argc, argv);

    NS_ABORT_MSG_IF(videoModel != "segments" && videoModel != "cbr", "video: segments or cbr");
    NS_ABORT_MSG_IF(association != "best" && association != "geometric",
                    "association: best or geometric");
    const bool best = association == "best";
    NS_ABORT_MSG_IF(scheduler != "ofdma" && scheduler != "tdma", "scheduler: ofdma or tdma");
    if (neighborScheduler.empty())
    {
        neighborScheduler = scheduler;
    }
    NS_ABORT_MSG_IF(neighborScheduler != "ofdma" && neighborScheduler != "tdma",
                    "neighborScheduler: ofdma or tdma");
    // SleepyScheduler extends the OFDMA scheduler: it would silently replace TDMA in cell 0.
    NS_ABORT_MSG_IF((scheduler == "tdma" || neighborScheduler == "tdma") && sleepTwMs > 0,
                    "the sleep mode is implemented and verified only with the ofdma scheduler");
    NS_ABORT_MSG_IF(g_olla.step > 0 && sleepTwMs > 0,
                    "outer loop link adaptation is not combined with the sleep mode");
    NS_ABORT_MSG_IF(g_olla.step < 0 || g_olla.target <= 0 || g_olla.target >= 1,
                    "ollaStep >= 0 and 0 < ollaTarget < 1");
    // Video rates [Mbit/s] of the first UEs of each site (720p, 1080p, 4K in Uitto et al.).
    std::vector<double> video;
    if (profile == "night")
    {
        loadMbps = loadMbps < 0 ? 1 : loadMbps;
        activeUes = activeUes < 0 ? 2 : activeUes;
    }
    else if (profile == "day")
    {
        loadMbps = loadMbps < 0 ? 40 : loadMbps;
        activeUes = activeUes < 0 ? uesPerGnb : activeUes;
    }
    else if (profile == "peak")
    {
        loadMbps = loadMbps < 0 ? 47 : loadMbps; // plus 53 of video: 100 in total
        activeUes = activeUes < 0 ? uesPerGnb : activeUes;
        video = {3, 10, 40};
    }
    else
    {
        NS_ABORT_MSG("profile: night, day or peak");
    }
    NS_ABORT_MSG_IF(activeUes > int(uesPerGnb) || activeUes <= int(video.size()),
                    "activeUes must exceed the video UEs and not exceed uesPerGnb");
    RngSeedManager::SetRun(run);
    g_warmup = Seconds(warmup);
    const Time stop = Seconds(warmup + duration);
    Config::SetDefault("ns3::NrRlcUm::MaxTxBufferSize", UintegerValue(20000000));

    NodeContainer gnbs(nGnb);
    NodeContainer ues;
    if (!best)
    {
        ues.Create(nGnb * uesPerGnb);
    }
    const double isd = 2 * radius;
    auto gnbPos = CreateObject<ListPositionAllocator>();
    auto uePos = CreateObject<ListPositionAllocator>();
    auto rnd = CreateObject<UniformRandomVariable>();
    rnd->SetStream(1);
    auto drop = [&](const Vector& c) {
        double r = sqrt(rnd->GetValue(35.0 * 35.0, radius * radius));
        double t = rnd->GetValue(0, 2 * M_PI);
        return Vector(c.x + r * cos(t), c.y + r * sin(t), 1.5);
    };
    for (uint32_t g = 0; g < nGnb; ++g)
    {
        // Site 0 at the origin, the others on a ring around it.
        double a = 2 * M_PI * g / 6.0;
        Vector c = g == 0 ? Vector(0, 0, 25) : Vector(isd * cos(a), isd * sin(a), 25);
        gnbPos->Add(c);
        for (uint32_t u = 0; !best && u < uesPerGnb; ++u)
        {
            uePos->Add(drop(c));
        }
    }
    MobilityHelper mob;
    mob.SetMobilityModel("ns3::ConstantPositionMobilityModel");
    mob.SetPositionAllocator(gnbPos);
    mob.Install(gnbs);
    mob.SetPositionAllocator(uePos);
    mob.Install(ues);

    auto epc = CreateObject<NrPointToPointEpcHelper>();
    auto bf = CreateObject<IdealBeamformingHelper>();
    auto nr = CreateObject<NrHelper>();
    nr->SetBeamformingHelper(bf);
    nr->SetEpcHelper(epc);
    bf->SetAttribute("BeamformingMethod", TypeIdValue(DirectPathBeamforming::GetTypeId()));
    epc->SetAttribute("S1uLinkDelay", TimeValue(MilliSeconds(0)));

    CcBwpCreator creator;
    CcBwpCreator::SimpleOperationBandConf conf(3.5e9, 2 * bwPerCarrier, 2);
    OperationBandInfo band = creator.CreateOperationBandContiguousCc(conf);
    auto ch = CreateObject<NrChannelHelper>();
    ch->ConfigureFactories("UMa", "Default", "ThreeGpp");
    ch->SetChannelConditionModelAttribute("UpdatePeriod", TimeValue(MilliSeconds(0)));
    ch->SetPathlossAttribute("ShadowingEnabled", BooleanValue(true));
    ch->AssignChannelsToBands({band});
    auto bwps = CcBwpCreator::GetAllBwps({band});
    if (sharedShadowing)
    {
        // The helper draws LOS and shadowing per carrier, but the carriers are contiguous: give
        // carrier 1 the pathloss and LOS models of carrier 0 (its 30 MHz offset is negligible).
        // Fast fading stays independent.
        auto loss = DynamicCast<ThreeGppPropagationLossModel>(
            bwps.at(0).get()->GetChannel()->GetPropagationLossModel());
        auto channel = ch->CreateChannel(NrChannelHelper::INIT_FADING);
        auto matrix = channel->GetPhasedArraySpectrumPropagationLossModel()
                          ->GetObject<MatrixBasedChannelModel>();
        matrix->SetAttribute("ChannelConditionModel", PointerValue(loss->GetChannelConditionModel()));
        matrix->SetAttribute("Frequency", DoubleValue(bwps.at(1).get()->m_centralFrequency));
        channel->AddPropagationLossModel(loss);
        bwps.at(1).get()->SetChannel(channel);
    }

    // Best-cell drop: the same pathloss objects (LOS state and shadowing are cached per node
    // pair) rank the sites here and are used in the run. Each UE is checked on the carrier that
    // serves it, because the models draw independent shadowing per carrier. Sites differ only in
    // pathloss and shadowing, so the choice does not depend on the active chains.
    uint32_t rejected = 0;
    for (uint32_t i = 0; best && i < nGnb * uesPerGnb; ++i)
    {
        const uint32_t own = i / uesPerGnb;
        auto loss = bwps.at(i % 2).get()->GetChannel()->GetPropagationLossModel();
        for (bool ok = false; !ok;)
        {
            auto n = CreateObject<Node>();
            auto m = CreateObject<ConstantPositionMobilityModel>();
            m->SetPosition(drop(gnbs.Get(own)->GetObject<MobilityModel>()->GetPosition()));
            n->AggregateObject(m);
            std::vector<double> rx;
            for (uint32_t g = 0; g < nGnb; ++g)
            {
                rx.push_back(loss->CalcRxPower(0, gnbs.Get(g)->GetObject<MobilityModel>(), m));
            }
            ok = std::max_element(rx.begin(), rx.end()) - rx.begin() == own;
            ok ? ues.Add(n) : void(rejected++);
            NS_ABORT_MSG_IF(rejected > 1000, "too many rejected UE positions");
        }
    }
    std::cout << "rejected_positions " << rejected << std::endl;

    // Array shape per number of chains, rows x columns of elements; 48 and 24 keep the array
    // no wider than 64 chains (8 columns).
    const std::map<uint32_t, std::pair<uint32_t, uint32_t>> shapes{{64, {8, 8}},
                                                                   {48, {6, 8}},
                                                                   {32, {4, 8}},
                                                                   {24, {4, 6}},
                                                                   {16, {4, 4}}};
    NS_ABORT_MSG_IF(!shapes.contains(antennas) || !shapes.contains(neighborAntennas),
                    "antennas: 64, 48, 32, 24 or 16");
    auto setGnbArray = [&](uint32_t chains) {
        const auto [rows, cols] = shapes.at(chains);
        // Dual polarization doubles the elements per position: halve the rows.
        nr->SetGnbAntennaAttribute("NumRows", UintegerValue(suMimo ? rows / 2 : rows));
        nr->SetGnbAntennaAttribute("NumColumns", UintegerValue(cols));
    };
    nr->SetGnbAntennaAttribute("AntennaElement",
                               PointerValue(CreateObject<IsotropicAntennaModel>()));
    nr->SetUeAntennaAttribute("NumRows", UintegerValue(1));
    nr->SetUeAntennaAttribute("NumColumns", UintegerValue(suMimo ? 1 : 2));
    nr->SetUeAntennaAttribute("AntennaElement",
                              PointerValue(CreateObject<IsotropicAntennaModel>()));
    if (suMimo)
    {
        nr->SetGnbAntennaAttribute("IsDualPolarized", BooleanValue(true));
        nr->SetUeAntennaAttribute("IsDualPolarized", BooleanValue(true));
        NrHelper::MimoPmiParams pmi; // full search, two-port codebook
        pmi.subbandSize = 8;
        pmi.rankLimit = 2;
        nr->SetupMimoPmi(pmi);
        nr->SetAttribute("CsiFeedbackFlags", UintegerValue(1));
    }
    nr->SetGnbBwpManagerAlgorithmAttribute("NGBR_LOW_LAT_EMBB", UintegerValue(0));
    nr->SetGnbBwpManagerAlgorithmAttribute("GBR_CONV_VOICE", UintegerValue(1));
    nr->SetUeBwpManagerAlgorithmAttribute("NGBR_LOW_LAT_EMBB", UintegerValue(0));
    nr->SetUeBwpManagerAlgorithmAttribute("GBR_CONV_VOICE", UintegerValue(1));
    if (sleepTwMs > 0)
    {
        g_sleep = Create<SleepController>(sleepTwMs, sleepSsbMs, sleepTimerTw);
        g_sleep->Start(g_warmup, stop);
    }

    g_cells.resize(nGnb);
    // Site by site: only cell 0 changes its number of chains.
    NetDeviceContainer gnbDev;
    for (uint32_t g = 0; g < nGnb; ++g)
    {
        setGnbArray(g == 0 ? antennas : neighborAntennas);
        nr->SetSchedulerTypeId(TypeId::LookupByName(
            g == 0 && g_sleep ? "ns3::SleepyScheduler"
            : (g == 0 ? scheduler : neighborScheduler) == "tdma"
                ? (g_olla.step > 0 ? "ns3::OllaTdma" : "ns3::NrMacSchedulerTdmaPF")
                : (g_olla.step > 0 ? "ns3::OllaOfdma" : "ns3::NrMacSchedulerOfdmaPF")));
        gnbDev.Add(nr->InstallGnbDevice(NodeContainer(gnbs.Get(g)), bwps));
    }
    auto ueDev = nr->InstallUeDevice(ues, bwps);
    int64_t stream = 100;
    stream += nr->AssignStreams(gnbDev, stream);
    stream += nr->AssignStreams(ueDev, stream);

    // With fewer chains each PA keeps its own maximum, so the total scales with the chains.
    for (uint32_t g = 0; g < nGnb; ++g)
    {
        const uint32_t chains = g == 0 ? antennas : neighborAntennas;
        const double perCarrierDbm = 10 * log10(peakTxW / 2 * chains / 64.0 * 1000);
        for (uint32_t c = 0; c < 2; ++c)
        {
            auto phy = NrHelper::GetGnbPhy(gnbDev.Get(g), c);
            phy->SetAttribute("Numerology", UintegerValue(1));
            phy->SetAttribute("TxPower", DoubleValue(perCarrierDbm));
            phy->SetAttribute("Pattern", StringValue("DL|DL|DL|S|UL|"));
            phy->TraceConnectWithoutContext("SlotDataStats", MakeBoundCallback(&CellData, g));
            if (g == 0)
            {
                phy->TraceConnectWithoutContext("SlotDataStats", MakeBoundCallback(&SlotData, c));
            }
        }
    }

    for (uint32_t i = 0; i < uesPerGnb; ++i) // only UEs of cell 0
    {
        for (uint32_t c = 0; c < 2; ++c)
        {
            NrHelper::GetUePhy(ueDev.Get(i), c)
                ->GetSpectrumPhy()
                ->TraceConnectWithoutContext("RxPacketTraceUe", MakeBoundCallback(&RxTb, i, c));
        }
    }

    auto [remote, remoteAddr] = epc->SetupRemoteHost("100Gb/s", 2500, Seconds(0));
    InternetStackHelper inet;
    inet.Install(ues);
    auto ifs = epc->AssignUeIpv4Address(NetDeviceContainer(ueDev));
    for (uint32_t i = 0; i < ues.GetN(); ++i)
    {
        // Geometric association: UE i belongs to the site it was dropped around.
        nr->AttachToGnb(ueDev.Get(i), gnbDev.Get(i / uesPerGnb));
    }

    std::vector<Ptr<BurstSource>> sources;
    std::vector<Ptr<CbrSource>> videos;
    std::map<uint32_t, Ptr<SegmentSource>> segments; // by UE index
    for (uint32_t i = 0; i < ues.GetN(); ++i)
    {
        const uint16_t port = 1234 + i % 2;
        auto tft = Create<NrEpcTft>();
        NrEpcTft::PacketFilter pf;
        pf.localPortStart = port;
        pf.localPortEnd = port;
        tft->Add(pf);
        nr->ActivateDedicatedEpsBearer(ueDev.Get(i),
                                       NrEpsBearer(i % 2 == 0 ? NrEpsBearer::NGBR_LOW_LAT_EMBB
                                                              : NrEpsBearer::GBR_CONV_VOICE),
                                       tft);
        PacketSinkHelper sink("ns3::UdpSocketFactory",
                              InetSocketAddress(Ipv4Address::GetAny(), port));
        auto sinkApps = sink.Install(ues.Get(i));
        sinkApps.Start(Seconds(0));
        const uint32_t k = i % uesPerGnb; // index inside the site
        if (k >= uint32_t(activeUes) || (k >= video.size() && loadMbps <= 0))
        {
            continue;
        }
        auto s = Socket::CreateSocket(remote, UdpSocketFactory::GetTypeId());
        s->Connect(InetSocketAddress(ifs.GetAddress(i), port));
        if (k < video.size() && videoModel == "segments")
        {
            auto src =
                Create<SegmentSource>(s, video[k] * 1e6, segmentS, videoPaceMbps * 1e6, stop);
            auto phase = CreateObject<UniformRandomVariable>();
            phase->SetStream(6000 + i);
            segments[i] = src;
            sinkApps.Get(0)->TraceConnectWithoutContext(
                "Rx",
                MakeCallback(&SegmentSource::Received, PeekPointer(src)));
            Simulator::Schedule(g_warmup,
                                &SegmentSource::Start,
                                src,
                                Seconds(phase->GetValue(0, segmentS)));
        }
        else if (k < video.size())
        {
            auto src = Create<CbrSource>(s, video[k] * 1e6, stop);
            videos.push_back(src);
            Simulator::Schedule(g_warmup, &CbrSource::Fire, src);
        }
        else
        {
            auto src = Create<BurstSource>(s,
                                           loadMbps * 1e6 / (activeUes - video.size()),
                                           burstBytes,
                                           stop,
                                           5000 + i);
            sources.push_back(src);
            Simulator::Schedule(g_warmup, &BurstSource::ScheduleNext, src);
        }
    }

    g_slots.open(out + "_slots.csv");
    NS_ABORT_MSG_IF(!g_slots.is_open(), "cannot open output");
    g_slots << "slot,carrier,ues,used_reg,used_sym,avail_rb,avail_sym\n";

    if (tbTrace)
    {
        g_tb.open(out + "_tb.csv");
        g_tb << "slot,ue,carrier,sym_start,syms,rbs,tb_bytes,mcs,rank,rv,sinr_db,sinr_min_db,tbler,"
                "corrupt,cqi\n";
    }

    FlowMonitorHelper fmh;
    NodeContainer ends(ues);
    ends.Add(remote);
    auto mon = fmh.Install(ends);
    mon->SetAttribute("DelayBinWidth", DoubleValue(0.0005));

    // Short drain so packets generated near the end are not counted as lost.
    Simulator::Stop(stop + Seconds(drain));
    Simulator::Run();

    mon->CheckForLostPackets();
    auto cls = DynamicCast<Ipv4FlowClassifier>(fmh.GetClassifier());
    std::ofstream f(out + "_flows.csv");
    f << "ue,tx_bytes,rx_bytes,tx_pkts,rx_pkts,delay_sum_s,delay_p95_s,kind\n";
    for (auto& [id, st] : mon->GetFlowStats())
    {
        auto t = cls->FindFlow(id);
        for (uint32_t i = 0; i < uesPerGnb; ++i) // only UEs of cell 0
        {
            if (t.destinationAddress != ifs.GetAddress(i))
            {
                continue;
            }
            double p95 = 0;
            uint64_t cum = 0;
            Histogram h = st.delayHistogram;
            for (uint32_t b = 0; b < h.GetNBins() && cum < 0.95 * st.rxPackets; ++b)
            {
                cum += h.GetBinCount(b);
                p95 = h.GetBinEnd(b);
            }
            f << i << ',' << st.txBytes << ',' << st.rxBytes << ',' << st.txPackets << ','
              << st.rxPackets << ',' << st.delaySum.GetSeconds() << ',' << p95 << ','
              << (i < video.size() ? "video" : "burst") << '\n';
        }
    }
    std::ofstream cl(out + "_cells.csv");
    cl << "cell,slots,used_reg,avail_reg,used_sym,avail_sym\n";
    for (uint32_t g = 0; g < nGnb; ++g)
    {
        const auto& c = g_cells[g];
        cl << g << ',' << c.slots << ',' << c.usedReg << ',' << c.availReg << ',' << c.usedSym << ','
           << c.availSym << '\n';
    }
    std::ofstream rx(out + "_rx.csv");
    rx << "ue,tbs,retx,corrupt,ok_bytes,res,sinr_db_w,mcs_w,rank_w,sym_sum,tbler_sum\n";
    for (const auto& [ue, s] : g_rx)
    {
        rx << ue << ',' << s.tbs << ',' << s.retx << ',' << s.corrupt << ',' << s.okBytes << ','
           << s.res << ',' << s.sinrDb << ',' << s.mcs << ',' << s.rank << ',' << s.syms << ','
           << s.tbler << '\n';
    }
    if (!segments.empty())
    {
        std::ofstream v(out + "_segments.csv");
        v << "ue,segment,start_s,pkts,sent,rx,last_rx_s\n";
        for (auto& [i, src] : segments)
        {
            if (i >= uesPerGnb) // only UEs of cell 0
            {
                continue;
            }
            uint32_t id = 0;
            for (auto& seg : src->Segments())
            {
                v << i << ',' << id++ << ',' << seg.start.GetSeconds() << ','
                  << src->PacketsPerSegment() << ',' << seg.sent << ',' << seg.rx << ','
                  << seg.lastRx.GetSeconds() << '\n';
            }
        }
    }
    if (g_sleep)
    {
        std::ofstream z(out + "_sleep.csv");
        g_sleep->Print(z);
        g_sleep = nullptr;
    }
    Simulator::Destroy();
    return 0;
}
