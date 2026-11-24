// Downlink scenario for base-station energy evaluation (5G-LENA).
//
// One AAU per site with two contiguous n78 carriers; UEs are statically split between
// the carriers through their QCI. Traffic profiles over UDP: night (few UEs, rare Poisson bursts),
// day (all UEs, Poisson bursts), peak (CBR video UEs, Poisson bursts on the others). The program
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
    cmd.AddValue("warmup", "Discarded initial time [s]", warmup);
    cmd.AddValue("duration", "Measured time [s]", duration);
    cmd.AddValue("run", "RNG run", run);
    cmd.AddValue("out", "Output file prefix", out);
    cmd.Parse(argc, argv);

    for (auto a : {antennas, neighborAntennas})
    {
        NS_ABORT_MSG_IF(a != 64 && a != 32 && a != 16, "antennas: 64, 32 or 16");
    }
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
        loadMbps = loadMbps < 0 ? 27 : loadMbps;
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
    NodeContainer ues(nGnb * uesPerGnb);
    const double isd = 2 * radius;
    auto gnbPos = CreateObject<ListPositionAllocator>();
    auto uePos = CreateObject<ListPositionAllocator>();
    auto rnd = CreateObject<UniformRandomVariable>();
    rnd->SetStream(1);
    for (uint32_t g = 0; g < nGnb; ++g)
    {
        // Site 0 at the origin, the others on a ring around it.
        double a = 2 * M_PI * g / 6.0;
        Vector c = g == 0 ? Vector(0, 0, 25) : Vector(isd * cos(a), isd * sin(a), 25);
        gnbPos->Add(c);
        for (uint32_t u = 0; u < uesPerGnb; ++u)
        {
            double r = sqrt(rnd->GetValue(35.0 * 35.0, radius * radius));
            double t = rnd->GetValue(0, 2 * M_PI);
            uePos->Add(Vector(c.x + r * cos(t), c.y + r * sin(t), 1.5));
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
        sink.Install(ues.Get(i)).Start(Seconds(0));
        const uint32_t k = i % uesPerGnb; // index inside the site
        if (k >= uint32_t(activeUes) || (k >= video.size() && loadMbps <= 0))
        {
            continue;
        }
        auto s = Socket::CreateSocket(remote, UdpSocketFactory::GetTypeId());
        s->Connect(InetSocketAddress(ifs.GetAddress(i), port));
        if (k < video.size())
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
    Simulator::Stop(stop + MilliSeconds(50));
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
    Simulator::Destroy();
    return 0;
}
