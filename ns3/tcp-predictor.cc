// Dumbbell simulation for comparing TCP variants under three congestion levels.
//
//   Sender 0 ─┐                                           ┌─ sink :5000
//   Sender 1 ─┤ 100 Mbps, 1 ms                            │
//      ...    ├── R1 ═══ 10 Mbps, 20 ms (FIFO 50p) ═══ R2 ─┤ ...
//   UDP node ─┘                                           └─ sink :9000
//
// Every 100 ms one CSV row is written per TCP flow with the sender's view
// (smoothed RTT, min RTT, cwnd, throughput, retransmissions, loss events, time
// since the last loss) and
// the bottleneck's view (max queue length in the interval, drops).
//
// Example:
//   ./ns3 run "tcp-predictor --variant=reno --level=high --seed=1 --outDir=/tmp"

#include "tcp-variants.h"

#include "ns3/applications-module.h"
#include "ns3/core-module.h"
#include "ns3/flow-monitor-module.h"
#include "ns3/internet-module.h"
#include "ns3/network-module.h"
#include "ns3/point-to-point-module.h"
#include "ns3/traffic-control-module.h"

#include <algorithm>
#include <deque>
#include <fstream>
#include <iomanip>

using namespace ns3;

NS_LOG_COMPONENT_DEFINE("TcpPredictor");

namespace
{

const double kSampleInterval = 0.1; // seconds
const double kLossWindow = 0.5;     // short loss-event window (s)
const double kLossWindowLong = 2.0; // long loss-event window (s)
const double kSinceLossCap = 10.0;  // "time since last loss" is capped here (s)
const uint16_t kTcpBasePort = 5000;
const uint16_t kUdpPort = 9000;

struct FlowState
{
    bool traced = false;
    double srttMs = 0;
    double minRttMs = 0;
    double rawMinRttMs = 0;       // lowest raw RTT sample so far
    double intervalMinRttMs = 0;  // lowest raw RTT sample in the current interval
    double lastIntervalMinMs = 0; // last interval that had a sample
    uint32_t cwnd = 0;
    uint64_t rxBytes = 0;
    uint64_t lastRxBytes = 0;
    uint32_t retxInterval = 0;
    uint64_t retxTotal = 0;
    std::deque<double> lossTimes;
    uint64_t lossEventsTotal = 0;
    double lastLossTime = -1; // -1 = no loss yet
};

std::vector<FlowState> g_flows;
uint32_t g_queueNow = 0;
uint32_t g_queueMaxInterval = 0;
uint32_t g_dropsInterval = 0;
uint64_t g_dropsTotal = 0;
uint32_t g_queueCap = 0;
std::ofstream g_samples;
bool g_traceCwnd = false;
std::ofstream g_cwndLog;
uint32_t g_ssthresh0 = 0;

void
RttTrace(uint32_t i, Time, Time newVal)
{
    double ms = newVal.GetSeconds() * 1000.0;
    if (ms <= 0)
    {
        return;
    }
    g_flows[i].srttMs = ms;
    if (g_flows[i].minRttMs == 0 || ms < g_flows[i].minRttMs)
    {
        g_flows[i].minRttMs = ms;
    }
}

void
LastRttTrace(uint32_t i, Time, Time newVal)
{
    double ms = newVal.GetSeconds() * 1000.0;
    if (ms <= 0)
    {
        return;
    }
    FlowState& f = g_flows[i];
    f.intervalMinRttMs = (f.intervalMinRttMs == 0) ? ms : std::min(f.intervalMinRttMs, ms);
    f.rawMinRttMs = (f.rawMinRttMs == 0) ? ms : std::min(f.rawMinRttMs, ms);
}

void
CwndTrace(uint32_t i, uint32_t, uint32_t newVal)
{
    g_flows[i].cwnd = newVal;
    if (g_traceCwnd && i == 0)
    {
        g_cwndLog << Simulator::Now().GetSeconds() << "," << newVal << "," << g_ssthresh0 << "\n";
    }
}

void
SsThreshTrace(uint32_t, uint32_t newVal)
{
    g_ssthresh0 = newVal;
}

void
CongStateTrace(uint32_t i, TcpSocketState::TcpCongState_t oldVal, TcpSocketState::TcpCongState_t newVal)
{
    bool enteredLoss = (newVal == TcpSocketState::CA_RECOVERY || newVal == TcpSocketState::CA_LOSS) &&
                       oldVal != newVal;
    if (enteredLoss)
    {
        g_flows[i].lossTimes.push_back(Simulator::Now().GetSeconds());
        g_flows[i].lossEventsTotal++;
        g_flows[i].lastLossTime = Simulator::Now().GetSeconds();
    }
}

void
RetxTrace(uint32_t i,
          Ptr<const Packet>,
          const TcpHeader&,
          const Address&,
          const Address&,
          Ptr<const TcpSocketBase>)
{
    g_flows[i].retxInterval++;
    g_flows[i].retxTotal++;
}

void
SinkRxTrace(uint32_t i, Ptr<const Packet> packet, const Address&)
{
    g_flows[i].rxBytes += packet->GetSize();
}

void
QueueTrace(uint32_t, uint32_t newVal)
{
    g_queueNow = newVal;
    g_queueMaxInterval = std::max(g_queueMaxInterval, newVal);
}

void
DropTrace(Ptr<const QueueDiscItem>)
{
    g_dropsInterval++;
    g_dropsTotal++;
}

void
ConnectSocketTraces(uint32_t flow, uint32_t nodeId)
{
    std::string base = "/NodeList/" + std::to_string(nodeId) + "/$ns3::TcpL4Protocol/SocketList/0/";
    Config::ConnectWithoutContext(base + "RTT", MakeBoundCallback(&RttTrace, flow));
    Config::ConnectWithoutContext(base + "LastRTT", MakeBoundCallback(&LastRttTrace, flow));
    Config::ConnectWithoutContext(base + "CongestionWindow", MakeBoundCallback(&CwndTrace, flow));
    Config::ConnectWithoutContext(base + "CongState", MakeBoundCallback(&CongStateTrace, flow));
    Config::ConnectWithoutContext(base + "Retransmission", MakeBoundCallback(&RetxTrace, flow));
    if (flow == 0)
    {
        Config::ConnectWithoutContext(base + "SlowStartThreshold", MakeCallback(&SsThreshTrace));
    }
    g_flows[flow].traced = true;
}

void
Sample(double stopTime)
{
    double now = Simulator::Now().GetSeconds();
    for (uint32_t i = 0; i < g_flows.size(); ++i)
    {
        FlowState& f = g_flows[i];
        while (!f.lossTimes.empty() && f.lossTimes.front() < now - kLossWindowLong)
        {
            f.lossTimes.pop_front();
        }
        size_t lossShort = 0;
        for (double t : f.lossTimes)
        {
            lossShort += (t >= now - kLossWindow) ? 1 : 0;
        }
        double thrMbps = (f.rxBytes - f.lastRxBytes) * 8.0 / kSampleInterval / 1e6;
        double sinceLoss =
            f.lastLossTime < 0 ? kSinceLossCap : std::min(kSinceLossCap, now - f.lastLossTime);
        f.lastRxBytes = f.rxBytes;

        if (f.intervalMinRttMs > 0)
        {
            f.lastIntervalMinMs = f.intervalMinRttMs;
        }
        if (f.traced && f.srttMs > 0)
        {
            g_samples << std::fixed << std::setprecision(3) << now << "," << i << "," << f.srttMs
                      << "," << f.minRttMs << "," << f.cwnd << "," << thrMbps << ","
                      << f.retxInterval << "," << lossShort << "," << f.lossTimes.size() << ","
                      << g_queueMaxInterval
                      << "," << g_queueCap << "," << g_dropsInterval << "," << sinceLoss << ","
                      << (f.lastIntervalMinMs > 0 ? f.lastIntervalMinMs : f.srttMs) << ","
                      << (f.rawMinRttMs > 0 ? f.rawMinRttMs : f.minRttMs) << "\n";
        }
        f.retxInterval = 0;
        f.intervalMinRttMs = 0;
    }
    g_queueMaxInterval = g_queueNow;
    g_dropsInterval = 0;

    if (now + kSampleInterval <= stopTime + 1e-9)
    {
        Simulator::Schedule(Seconds(kSampleInterval), &Sample, stopTime);
    }
}

// Congestion control and loss recovery for a variant name
void
ResolveVariant(const std::string& name, TypeId& cc, TypeId& recovery)
{
    if (name == "tahoe")
    {
        cc = TcpTahoe::GetTypeId();
        recovery = TcpTahoeRecovery::GetTypeId();
    }
    else if (name == "reno")
    {
        cc = TcpReno::GetTypeId();
        recovery = TcpRenoRecovery::GetTypeId();
    }
    else if (name == "cubic")
    {
        cc = TcpCubic::GetTypeId();
        recovery = TcpClassicRecovery::GetTypeId();
    }
    else if (name == "vegas")
    {
        // Delay-based: keeps 2-4 extra packets queued, measured from RTT
        cc = TcpVegas::GetTypeId();
        recovery = TcpClassicRecovery::GetTypeId();
    }
    else if (name == "bbr")
    {
        // Model-based: paces at the estimated bottleneck bandwidth. It uses PRR
        // recovery as in NS-3's own BBR example.
        cc = TcpBbr::GetTypeId();
        recovery = TcpPrrRecovery::GetTypeId();
    }
    else if (name == "predictive")
    {
        // Reno's loss recovery, so any difference from Reno comes from the predictor
        cc = TcpPredictive::GetTypeId();
        recovery = TcpRenoRecovery::GetTypeId();
    }
    else
    {
        NS_FATAL_ERROR("Unknown variant: " << name);
    }
}

} // namespace

int
main(int argc, char* argv[])
{
    std::string variant = "reno";
    std::string level = "medium";
    uint32_t seed = 1;
    double simTime = 60.0;
    std::string bottleneckRate = "10Mbps";
    std::string bottleneckDelay = "20ms";
    uint32_t queueSize = 50;
    std::string outDir = ".";
    bool sack = true;
    std::string recoveryName = "";
    std::string mix = "";

    CommandLine cmd(__FILE__);
    cmd.AddValue("variant", "tahoe | reno | cubic | vegas | bbr | predictive", variant);
    cmd.AddValue("level", "low | medium | high | single", level);
    cmd.AddValue("seed", "Random run number", seed);
    cmd.AddValue("simTime", "Simulation time (s)", simTime);
    cmd.AddValue("rate", "Bottleneck data rate", bottleneckRate);
    cmd.AddValue("delay", "Bottleneck one-way delay", bottleneckDelay);
    cmd.AddValue("queue", "Bottleneck queue size (packets)", queueSize);
    cmd.AddValue("outDir", "Directory for CSV output", outDir);
    cmd.AddValue("sack", "Enable SACK", sack);
    cmd.AddValue("recovery", "Override recovery type (e.g. ns3::TcpPrrRecovery)", recoveryName);
    cmd.AddValue("mix",
                 "Second variant for a mixed run: odd-numbered TCP flows use it, even-numbered "
                 "flows use --variant (e.g. --variant=predictive --mix=cubic)",
                 mix);
    cmd.AddValue("traceCwnd", "Log every cwnd change of flow 0", g_traceCwnd);
    cmd.Parse(argc, argv);

    RngSeedManager::SetSeed(1);
    RngSeedManager::SetRun(seed);

    // ---- TCP variant -------------------------------------------------------
    TypeId cc;
    TypeId recovery;
    ResolveVariant(variant, cc, recovery);
    if (variant == "bbr" && mix.empty())
    {
        Config::SetDefault("ns3::TcpSocketState::EnablePacing", BooleanValue(true)); // BBR needs pacing
    }
    Config::SetDefault("ns3::TcpL4Protocol::SocketType", TypeIdValue(cc));
    if (!recoveryName.empty())
    {
        recovery = TypeId::LookupByName(recoveryName);
    }
    Config::SetDefault("ns3::TcpL4Protocol::RecoveryType", TypeIdValue(recovery));

    // Same settings for every variant
    Config::SetDefault("ns3::TcpSocket::SegmentSize", UintegerValue(1448));
    Config::SetDefault("ns3::TcpSocket::SndBufSize", UintegerValue(4 << 20));
    Config::SetDefault("ns3::TcpSocket::RcvBufSize", UintegerValue(4 << 20));
    Config::SetDefault("ns3::TcpSocketBase::Sack", BooleanValue(sack));
    // Minimum RTO stays at the RFC 6298 value of 1 s. With 200 ms it equals the
    // receiver's delayed-ACK timer, and a one-segment window (Tahoe after a loss)
    // then times out on every packet and never recovers.
    Config::SetDefault("ns3::TcpSocketBase::MinRto", TimeValue(Seconds(1)));

    // ---- Traffic per congestion level --------------------------------------
    uint32_t nOnOff = 0;
    uint32_t nBulk = 0;
    std::string onOffRate;
    bool udpBackground = false;
    if (level == "low")
    {
        nOnOff = 3;
        onOffRate = "2Mbps";
    }
    else if (level == "medium")
    {
        nOnOff = 6;
        onOffRate = "3Mbps";
    }
    else if (level == "high")
    {
        nBulk = 8;
        udpBackground = true;
    }
    else if (level == "single")
    {
        nBulk = 1; // one long flow alone, used to validate the variants
    }
    else
    {
        NS_FATAL_ERROR("Unknown level: " << level);
    }
    uint32_t nTcp = nOnOff + nBulk;
    uint32_t nSenders = nTcp + (udpBackground ? 1 : 0);
    g_flows.resize(nTcp);

    // ---- Topology ----------------------------------------------------------
    NodeContainer senders;
    senders.Create(nSenders);
    NodeContainer routers;
    routers.Create(2);
    NodeContainer receiver;
    receiver.Create(1);

    PointToPointHelper access;
    access.SetDeviceAttribute("DataRate", StringValue("100Mbps"));
    access.SetChannelAttribute("Delay", StringValue("1ms"));

    PointToPointHelper bottleneck;
    bottleneck.SetDeviceAttribute("DataRate", StringValue(bottleneckRate));
    bottleneck.SetChannelAttribute("Delay", StringValue(bottleneckDelay));
    bottleneck.SetQueue("ns3::DropTailQueue", "MaxSize", StringValue("1p"));

    InternetStackHelper stack;
    stack.InstallAll();

    std::vector<NetDeviceContainer> senderLinks;
    for (uint32_t i = 0; i < nSenders; ++i)
    {
        senderLinks.push_back(access.Install(senders.Get(i), routers.Get(0)));
    }
    NetDeviceContainer coreLink = bottleneck.Install(routers.Get(0), routers.Get(1));
    NetDeviceContainer recvLink = access.Install(routers.Get(1), receiver.Get(0));

    // FIFO queue on R1 -> R2 (installed before addressing so it replaces the default)
    TrafficControlHelper tch;
    tch.SetRootQueueDisc("ns3::FifoQueueDisc",
                         "MaxSize",
                         QueueSizeValue(QueueSize(QueueSizeUnit::PACKETS, queueSize)));
    QueueDiscContainer qdiscs = tch.Install(coreLink.Get(0));
    g_queueCap = queueSize;

    Ipv4AddressHelper address;
    for (uint32_t i = 0; i < nSenders; ++i)
    {
        std::string net = "10.1." + std::to_string(i + 1) + ".0";
        address.SetBase(net.c_str(), "255.255.255.0");
        address.Assign(senderLinks[i]);
    }
    address.SetBase("10.2.1.0", "255.255.255.0");
    address.Assign(coreLink);
    address.SetBase("10.3.1.0", "255.255.255.0");
    Ipv4InterfaceContainer recvIf = address.Assign(recvLink);
    Ipv4Address sinkAddr = recvIf.GetAddress(1);
    Ipv4GlobalRoutingHelper::PopulateRoutingTables();

    qdiscs.Get(0)->TraceConnectWithoutContext("PacketsInQueue", MakeCallback(&QueueTrace));
    qdiscs.Get(0)->TraceConnectWithoutContext("Drop", MakeCallback(&DropTrace));

    // ---- Mixed run: odd-numbered TCP flows use the second variant ------------
    // (BBR turns pacing on for its own sockets, so no global pacing is set here)
    if (!mix.empty())
    {
        TypeId mixCc;
        TypeId mixRecovery;
        ResolveVariant(mix, mixCc, mixRecovery);
        for (uint32_t i = 1; i < nTcp; i += 2)
        {
            Ptr<TcpL4Protocol> tcp = senders.Get(i)->GetObject<TcpL4Protocol>();
            tcp->SetAttribute("SocketType", TypeIdValue(mixCc));
            tcp->SetAttribute("RecoveryType", TypeIdValue(mixRecovery));
        }
    }

    // ---- Applications ------------------------------------------------------
    Ptr<UniformRandomVariable> startRv = CreateObject<UniformRandomVariable>();
    startRv->SetAttribute("Min", DoubleValue(0.1));
    startRv->SetAttribute("Max", DoubleValue(2.0));
    std::string onTime = "ns3::ExponentialRandomVariable[Mean=1.0|Bound=5.0]";
    std::string offTime = "ns3::ExponentialRandomVariable[Mean=1.0|Bound=5.0]";

    for (uint32_t i = 0; i < nTcp; ++i)
    {
        uint16_t port = kTcpBasePort + i;
        PacketSinkHelper sinkHelper("ns3::TcpSocketFactory",
                                    InetSocketAddress(Ipv4Address::GetAny(), port));
        ApplicationContainer sinkApp = sinkHelper.Install(receiver.Get(0));
        sinkApp.Start(Seconds(0.0));
        sinkApp.Get(0)->TraceConnectWithoutContext("Rx", MakeBoundCallback(&SinkRxTrace, i));

        AddressValue remote(InetSocketAddress(sinkAddr, port));
        ApplicationContainer srcApp;
        if (i < nBulk)
        {
            BulkSendHelper bulk("ns3::TcpSocketFactory", Address());
            bulk.SetAttribute("Remote", remote);
            bulk.SetAttribute("MaxBytes", UintegerValue(0));
            bulk.SetAttribute("SendSize", UintegerValue(1448));
            srcApp = bulk.Install(senders.Get(i));
        }
        else
        {
            OnOffHelper onoff("ns3::TcpSocketFactory", Address());
            onoff.SetAttribute("Remote", remote);
            onoff.SetAttribute("DataRate", StringValue(onOffRate));
            onoff.SetAttribute("PacketSize", UintegerValue(1448));
            onoff.SetAttribute("OnTime", StringValue(onTime));
            onoff.SetAttribute("OffTime", StringValue(offTime));
            srcApp = onoff.Install(senders.Get(i));
        }
        double start = startRv->GetValue();
        srcApp.Start(Seconds(start));
        srcApp.Stop(Seconds(simTime));
        // The socket only exists once the application has started
        Simulator::Schedule(Seconds(start + 0.001),
                            &ConnectSocketTraces,
                            i,
                            senders.Get(i)->GetId());
    }

    if (udpBackground)
    {
        PacketSinkHelper udpSink("ns3::UdpSocketFactory",
                                 InetSocketAddress(Ipv4Address::GetAny(), kUdpPort));
        udpSink.Install(receiver.Get(0)).Start(Seconds(0.0));
        OnOffHelper udp("ns3::UdpSocketFactory", InetSocketAddress(sinkAddr, kUdpPort));
        udp.SetAttribute("DataRate", StringValue("2Mbps"));
        udp.SetAttribute("PacketSize", UintegerValue(1448));
        udp.SetAttribute("OnTime", StringValue(onTime));
        udp.SetAttribute("OffTime", StringValue(offTime));
        ApplicationContainer udpApp = udp.Install(senders.Get(nSenders - 1));
        udpApp.Start(Seconds(1.0));
        udpApp.Stop(Seconds(simTime));
    }

    // ---- Output ------------------------------------------------------------
    std::string tag = (mix.empty() ? variant : variant + "-vs-" + mix) + "_" + level + "_s" +
                      std::to_string(seed);
    g_samples.open(outDir + "/samples_" + tag + ".csv");
    g_samples << "time,flow,srtt_ms,min_rtt_ms,cwnd_bytes,thr_mbps,retx,loss_events_05s,"
                 "loss_events_2s,queue_pkts,queue_cap,drops,since_loss_s,rtt_min_int_ms,raw_min_rtt_ms\n";
    Simulator::Schedule(Seconds(kSampleInterval), &Sample, simTime);
    if (g_traceCwnd)
    {
        g_cwndLog.open(outDir + "/cwnd_" + tag + ".csv");
        g_cwndLog << "time,cwnd_bytes,ssthresh_bytes\n";
    }

    FlowMonitorHelper fmHelper;
    Ptr<FlowMonitor> monitor = fmHelper.InstallAll();

    Simulator::Stop(Seconds(simTime + 1.0));
    Simulator::Run();

    // ---- Per-flow summary (FlowMonitor) -----------------------------------
    monitor->CheckForLostPackets();
    Ptr<Ipv4FlowClassifier> classifier = DynamicCast<Ipv4FlowClassifier>(fmHelper.GetClassifier());
    std::ofstream fm(outDir + "/flowmon_" + tag + ".csv");
    fm << "flow,protocol,tx_packets,rx_packets,lost_packets,throughput_mbps,mean_delay_ms,"
          "retransmissions,loss_events\n";
    for (const auto& [id, st] : monitor->GetFlowStats())
    {
        Ipv4FlowClassifier::FiveTuple t = classifier->FindFlow(id);
        bool tcpData = t.protocol == 6 && t.destinationPort >= kTcpBasePort &&
                       t.destinationPort < kTcpBasePort + nTcp;
        bool udpData = t.protocol == 17 && t.destinationPort == kUdpPort;
        if (!tcpData && !udpData)
        {
            continue;
        }
        double duration = (st.timeLastRxPacket - st.timeFirstTxPacket).GetSeconds();
        double thr = duration > 0 ? st.rxBytes * 8.0 / duration / 1e6 : 0;
        double delay = st.rxPackets > 0 ? st.delaySum.GetSeconds() * 1000.0 / st.rxPackets : 0;
        int flow = tcpData ? t.destinationPort - kTcpBasePort : -1;
        fm << flow << "," << (tcpData ? "tcp" : "udp") << "," << st.txPackets << ","
           << st.rxPackets << "," << st.lostPackets << "," << thr << "," << delay << ","
           << (tcpData ? g_flows[flow].retxTotal : 0) << ","
           << (tcpData ? g_flows[flow].lossEventsTotal : 0) << "\n";
    }

    double totalRx = 0;
    uint64_t totalRetx = 0;
    for (const auto& f : g_flows)
    {
        totalRx += f.rxBytes;
        totalRetx += f.retxTotal;
    }
    std::cout << tag << ": goodput " << std::fixed << std::setprecision(2)
              << totalRx * 8.0 / simTime / 1e6 << " Mbps, retransmissions " << totalRetx
              << ", bottleneck drops " << g_dropsTotal
              << ", proactive reductions " << TcpPredictive::GetProactiveReductions()
              << ", competitive mode " << TcpPredictive::GetCompetitivePercent() << "%" << std::endl;

    std::ofstream info(outDir + "/runinfo_" + tag + ".csv");
    info << "goodput_mbps,retransmissions,drops,proactive_reductions,competitive_mode_pct\n"
         << totalRx * 8.0 / simTime / 1e6 << "," << totalRetx << "," << g_dropsTotal << ","
         << TcpPredictive::GetProactiveReductions() << ","
         << TcpPredictive::GetCompetitivePercent() << "\n";

    Simulator::Destroy();
    return 0;
}
