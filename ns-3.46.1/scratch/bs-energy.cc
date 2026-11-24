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

#include <fstream>

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
    bool sharedShadowing = true; // same LOS state and shadowing on both carriers
    double warmup = 0.3;
    double duration = 1.0;
    uint32_t run = 1;
    std::string out = "run";

    CommandLine cmd(__FILE__);
    cmd.AddValue("profile", "night, day or peak", profile);
    cmd.AddValue("loadMbps", "Offered DL burst load per cell [Mbit/s]", loadMbps);
    cmd.AddValue("activeUes", "UEs with traffic per site", activeUes);
    cmd.AddValue("antennas", "Active RF chains of cell 0 (64, 32, 16)", antennas);
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
    cmd.AddValue("drain", "Extra time after the last transmission [s]", drain);
    cmd.AddValue("warmup", "Discarded initial time [s]", warmup);
    cmd.AddValue("duration", "Measured time [s]", duration);
    cmd.AddValue("run", "RNG run", run);
    cmd.AddValue("out", "Output file prefix", out);
    cmd.Parse(argc, argv);

    for (auto a : {antennas, neighborAntennas})
    {
        NS_ABORT_MSG_IF(a != 64 && a != 32 && a != 16, "antennas: 64, 32 or 16");
    }
    NS_ABORT_MSG_IF(videoModel != "segments" && videoModel != "cbr", "video: segments or cbr");
    NS_ABORT_MSG_IF(association != "best" && association != "geometric",
                    "association: best or geometric");
    const bool best = association == "best";
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

    auto setGnbArray = [&](uint32_t chains) {
        const uint32_t rows = chains == 64 ? 8 : 4;
        // Dual polarization doubles the elements per position: halve the rows.
        nr->SetGnbAntennaAttribute("NumRows", UintegerValue(suMimo ? rows / 2 : rows));
        nr->SetGnbAntennaAttribute("NumColumns", UintegerValue(chains / rows));
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
    nr->SetSchedulerTypeId(TypeId::LookupByName("ns3::NrMacSchedulerOfdmaPF"));

    // Site by site: only cell 0 changes its number of chains.
    NetDeviceContainer gnbDev;
    for (uint32_t g = 0; g < nGnb; ++g)
    {
        setGnbArray(g == 0 ? antennas : neighborAntennas);
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
            if (g == 0)
            {
                phy->TraceConnectWithoutContext("SlotDataStats", MakeBoundCallback(&SlotData, c));
            }
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
    Simulator::Destroy();
    return 0;
}
