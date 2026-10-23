#include "tcp-variants.h"

#include "predictive-model.h"

#include "ns3/boolean.h"
#include "ns3/double.h"
#include "ns3/log.h"
#include "ns3/simulator.h"
#include "ns3/uinteger.h"

#include <algorithm>
#include <cmath>
#include <numeric>

namespace ns3
{

NS_LOG_COMPONENT_DEFINE("TcpVariants");

// ---------------------------------------------------------------- TcpTahoe

NS_OBJECT_ENSURE_REGISTERED(TcpTahoe);

TypeId
TcpTahoe::GetTypeId()
{
    static TypeId tid = TypeId("ns3::TcpTahoe")
                            .SetParent<TcpLinuxReno>()
                            .SetGroupName("Internet")
                            .AddConstructor<TcpTahoe>();
    return tid;
}

TcpTahoe::TcpTahoe()
    : TcpLinuxReno()
{
}

TcpTahoe::TcpTahoe(const TcpTahoe& sock)
    : TcpLinuxReno(sock)
{
}

std::string
TcpTahoe::GetName() const
{
    return "TcpTahoe";
}

Ptr<TcpCongestionOps>
TcpTahoe::Fork()
{
    return CopyObject<TcpTahoe>(this);
}

// ----------------------------------------------------------------- TcpReno

NS_OBJECT_ENSURE_REGISTERED(TcpReno);

TypeId
TcpReno::GetTypeId()
{
    static TypeId tid = TypeId("ns3::TcpReno")
                            .SetParent<TcpLinuxReno>()
                            .SetGroupName("Internet")
                            .AddConstructor<TcpReno>();
    return tid;
}

TcpReno::TcpReno()
    : TcpLinuxReno()
{
}

TcpReno::TcpReno(const TcpReno& sock)
    : TcpLinuxReno(sock)
{
}

std::string
TcpReno::GetName() const
{
    return "TcpReno";
}

Ptr<TcpCongestionOps>
TcpReno::Fork()
{
    return CopyObject<TcpReno>(this);
}

// -------------------------------------------------------- TcpTahoeRecovery

NS_OBJECT_ENSURE_REGISTERED(TcpTahoeRecovery);

TypeId
TcpTahoeRecovery::GetTypeId()
{
    static TypeId tid = TypeId("ns3::TcpTahoeRecovery")
                            .SetParent<TcpRecoveryOps>()
                            .SetGroupName("Internet")
                            .AddConstructor<TcpTahoeRecovery>();
    return tid;
}

TcpTahoeRecovery::TcpTahoeRecovery()
    : TcpRecoveryOps()
{
}

TcpTahoeRecovery::TcpTahoeRecovery(const TcpTahoeRecovery& recovery)
    : TcpRecoveryOps(recovery)
{
}

std::string
TcpTahoeRecovery::GetName() const
{
    return "TcpTahoeRecovery";
}

void
TcpTahoeRecovery::EnterRecovery(Ptr<TcpSocketState> tcb,
                                uint32_t dupAckCount [[maybe_unused]],
                                uint32_t unAckDataCount [[maybe_unused]],
                                uint32_t deliveredBytes [[maybe_unused]])
{
    // ssthresh has already been halved by GetSsThresh(); Tahoe has no fast
    // recovery, so the window collapses to a single segment.
    tcb->m_cWnd = tcb->m_segmentSize;
    tcb->m_cWndInfl = tcb->m_segmentSize;
}

void
TcpTahoeRecovery::DoRecovery(Ptr<TcpSocketState> tcb,
                             uint32_t deliveredBytes [[maybe_unused]],
                             bool isDupAck)
{
    // No window inflation on duplicate ACKs. Every ACK for new data (a partial
    // ACK) is treated as slow start, as Tahoe does after a fast retransmit.
    if (!isDupAck)
    {
        tcb->m_cWnd = std::min<uint32_t>(tcb->m_cWnd + tcb->m_segmentSize, tcb->m_ssThresh);
        tcb->m_cWndInfl = tcb->m_cWnd;
    }
}

void
TcpTahoeRecovery::ExitRecovery(Ptr<TcpSocketState> tcb)
{
    // The socket resets cwnd to ssthresh just before this call; undo that so
    // the sender slow-starts from one segment up to ssthresh.
    tcb->m_cWnd = tcb->m_segmentSize;
    tcb->m_cWndInfl = tcb->m_segmentSize;
}

Ptr<TcpRecoveryOps>
TcpTahoeRecovery::Fork()
{
    return CopyObject<TcpTahoeRecovery>(this);
}

// --------------------------------------------------------- TcpRenoRecovery

NS_OBJECT_ENSURE_REGISTERED(TcpRenoRecovery);

TypeId
TcpRenoRecovery::GetTypeId()
{
    static TypeId tid = TypeId("ns3::TcpRenoRecovery")
                            .SetParent<TcpRecoveryOps>()
                            .SetGroupName("Internet")
                            .AddConstructor<TcpRenoRecovery>();
    return tid;
}

TcpRenoRecovery::TcpRenoRecovery()
    : TcpRecoveryOps()
{
}

TcpRenoRecovery::TcpRenoRecovery(const TcpRenoRecovery& recovery)
    : TcpRecoveryOps(recovery)
{
}

std::string
TcpRenoRecovery::GetName() const
{
    return "TcpRenoRecovery";
}

void
TcpRenoRecovery::EnterRecovery(Ptr<TcpSocketState> tcb,
                               uint32_t dupAckCount,
                               uint32_t unAckDataCount [[maybe_unused]],
                               uint32_t deliveredBytes [[maybe_unused]])
{
    // Fast recovery: cwnd = ssthresh, inflated by the duplicate ACKs seen.
    tcb->m_cWnd = tcb->m_ssThresh;
    tcb->m_cWndInfl = tcb->m_ssThresh + (dupAckCount * tcb->m_segmentSize);
}

void
TcpRenoRecovery::DoRecovery(Ptr<TcpSocketState> tcb,
                            uint32_t deliveredBytes [[maybe_unused]],
                            bool isDupAck)
{
    if (isDupAck)
    {
        tcb->m_cWndInfl += tcb->m_segmentSize;
        return;
    }

    // Partial ACK: classic Reno would leave fast recovery here and treat the
    // next missing segment as a fresh loss, halving the window once more.
    uint32_t halved = std::max<uint32_t>(2 * tcb->m_segmentSize, tcb->m_cWnd / 2);
    tcb->m_ssThresh = halved;
    tcb->m_cWnd = halved;
    tcb->m_cWndInfl = halved;
}

void
TcpRenoRecovery::ExitRecovery(Ptr<TcpSocketState> tcb)
{
    tcb->m_cWndInfl = tcb->m_ssThresh.Get();
}

Ptr<TcpRecoveryOps>
TcpRenoRecovery::Fork()
{
    return CopyObject<TcpRenoRecovery>(this);
}


// ----------------------------------------------------------- TcpPredictive

NS_OBJECT_ENSURE_REGISTERED(TcpPredictive);

uint64_t TcpPredictive::s_proactiveReductions = 0;
uint64_t TcpPredictive::s_evaluations = 0;
uint64_t TcpPredictive::s_competitiveEvaluations = 0;

TypeId
TcpPredictive::GetTypeId()
{
    static TypeId tid =
        TypeId("ns3::TcpPredictive")
            .SetParent<TcpLinuxReno>()
            .SetGroupName("Internet")
            .AddConstructor<TcpPredictive>()
            // Beta and MinWindow were tuned on training seeds 1-3 (analysis/tune_controller.py)
            .AddAttribute("Beta",
                          "Window multiplier applied when High congestion is predicted",
                          DoubleValue(0.8),
                          MakeDoubleAccessor(&TcpPredictive::m_beta),
                          MakeDoubleChecker<double>(0.1, 1.0))
            .AddAttribute("Interval",
                          "How often the congestion model is evaluated",
                          TimeValue(MilliSeconds(100)),
                          MakeTimeAccessor(&TcpPredictive::m_interval),
                          MakeTimeChecker())
            .AddAttribute("HoldOnMedium",
                          "Slow down window growth when Medium congestion is predicted",
                          BooleanValue(true),
                          MakeBooleanAccessor(&TcpPredictive::m_holdOnMedium),
                          MakeBooleanChecker())
            .AddAttribute("MediumGrowth",
                          "Fraction of Reno's window growth allowed while Medium congestion "
                          "is predicted (0 freezes the window). Some growth keeps flows "
                          "converging to a fair share.",
                          DoubleValue(0.25),
                          MakeDoubleAccessor(&TcpPredictive::m_mediumGrowth),
                          MakeDoubleChecker<double>(0.0, 1.0))
            .AddAttribute("MinWindow",
                          "Window (segments) below which the predictor never holds or "
                          "reduces cwnd. With a tiny window the receiver's delayed ACKs "
                          "inflate the RTT and would look like congestion.",
                          UintegerValue(4),
                          MakeUintegerAccessor(&TcpPredictive::m_minWindow),
                          MakeUintegerChecker<uint32_t>(1))
            // Competition detector (Phase 8b, re-tuned in Phase 10 with the raw-RTT base;
            // defaults chosen on seeds 1-3 by analysis/tune_competition.py). When only Predictive flows share the
            // bottleneck, their cuts let the queue drain now and then. A loss-based
            // sender keeps it full until packets drop, so if the lowest RTT seen over
            // the whole window stays above the threshold, the sender behaves like
            // plain Reno until the queue drains again.
            .AddAttribute("CompetitionWindow",
                          "How long the queue must stay non-empty before a loss-based "
                          "competitor is assumed (0 turns the detector off)",
                          TimeValue(Seconds(2)),
                          MakeTimeAccessor(&TcpPredictive::m_compWindow),
                          MakeTimeChecker())
            .AddAttribute("CompetitionThreshold",
                          "Lowest RTT in the window divided by the base RTT above which a "
                          "competitor is assumed",
                          DoubleValue(1.4),
                          MakeDoubleAccessor(&TcpPredictive::m_compThreshold),
                          MakeDoubleChecker<double>(1.0))
            .AddAttribute("CompetitionHold",
                          "Stay in competitive mode at least this long after the queue was "
                          "last seen not draining (a loss-based competitor drains the queue "
                          "briefly after its own losses)",
                          TimeValue(Seconds(5)),
                          MakeTimeAccessor(&TcpPredictive::m_compHold),
                          MakeTimeChecker())
            // Phase 10. The competition detector needs the true base RTT. The lowest
            // *smoothed* RTT never gets there for a flow that starts behind a standing
            // queue (e.g. one held by CUBIC), so that flow's threshold sits above the
            // RTT it sees and it never detects the competitor. The lowest raw RTT
            // sample does reach the base, because the queue dips briefly now and then.
            // MinRttSignal is an experiment, off by default: it feeds the model the
            // lowest raw RTT of each interval, which delayed ACKs do not inflate for
            // small windows (fair on fast or long links), but the deployed tree was
            // trained on the smoothed RTT and loses much of its drop reduction with it
            // (see README, Phase 10).
            .AddAttribute("MinRttSignal",
                          "Experimental: model features use the lowest raw RTT sample of each "
                          "interval and the lowest raw RTT as the base RTT (the deployed tree was "
                          "trained on the smoothed RTT)",
                          BooleanValue(false),
                          MakeBooleanAccessor(&TcpPredictive::m_minRttSignal),
                          MakeBooleanChecker())
            .AddAttribute("DetectorRawBase",
                          "The competition detector compares against the lowest raw RTT sample "
                          "(false = lowest smoothed RTT, as in Phase 8b)",
                          BooleanValue(true),
                          MakeBooleanAccessor(&TcpPredictive::m_detectorRawBase),
                          MakeBooleanChecker());
    return tid;
}

TcpPredictive::TcpPredictive()
    : TcpLinuxReno(),
      m_beta(0.8),
      m_interval(MilliSeconds(100)),
      m_holdOnMedium(true),
      m_mediumGrowth(0.25),
      m_minWindow(4),
      m_compWindow(Seconds(2)),
      m_compThreshold(1.4),
      m_compHold(Seconds(5)),
      m_detectorRawBase(true),
      m_minRttSignal(false)
{
}

TcpPredictive::TcpPredictive(const TcpPredictive& sock)
    : TcpLinuxReno(sock),
      m_beta(sock.m_beta),
      m_interval(sock.m_interval),
      m_holdOnMedium(sock.m_holdOnMedium),
      m_mediumGrowth(sock.m_mediumGrowth),
      m_minWindow(sock.m_minWindow),
      m_compWindow(sock.m_compWindow),
      m_compThreshold(sock.m_compThreshold),
      m_compHold(sock.m_compHold),
      m_detectorRawBase(sock.m_detectorRawBase),
      m_minRttSignal(sock.m_minRttSignal)
{
}

std::string
TcpPredictive::GetName() const
{
    return "TcpPredictive";
}

uint64_t
TcpPredictive::GetProactiveReductions()
{
    return s_proactiveReductions;
}

double
TcpPredictive::GetCompetitivePercent()
{
    return s_evaluations ? 100.0 * s_competitiveEvaluations / s_evaluations : 0.0;
}

void
TcpPredictive::ResetProactiveReductions()
{
    s_proactiveReductions = 0;
}

void
TcpPredictive::CongestionStateSet(Ptr<TcpSocketState> tcb,
                                  const TcpSocketState::TcpCongState_t newState)
{
    // Count a loss event when the sender enters fast recovery or a timeout
    // (the same events the training data counted).
    bool lossState = newState == TcpSocketState::CA_RECOVERY || newState == TcpSocketState::CA_LOSS;
    if (lossState && tcb->m_congState != newState)
    {
        m_lossTimes.push_back(Simulator::Now().GetSeconds());
        m_lastLossTime = Simulator::Now().GetSeconds();
    }
    TcpLinuxReno::CongestionStateSet(tcb, newState);
}

void
TcpPredictive::PktsAcked(Ptr<TcpSocketState> tcb, uint32_t segmentsAcked, const Time& rtt)
{
    TcpLinuxReno::PktsAcked(tcb, segmentsAcked, rtt);

    double ms = rtt.GetSeconds() * 1000.0; // the socket passes its smoothed RTT
    if (ms > 0)
    {
        m_srttMs = ms;
        m_minRttMs = (m_minRttMs == 0) ? ms : std::min(m_minRttMs, ms);
    }
    m_ackedBytes += static_cast<uint64_t>(segmentsAcked) * tcb->m_segmentSize;
    double lastMs = tcb->m_lastRtt.Get().GetSeconds() * 1000.0; // latest raw RTT sample
    if (lastMs > 0)
    {
        m_intervalMinRttMs = (m_intervalMinRttMs == 0) ? lastMs : std::min(m_intervalMinRttMs, lastMs);
        m_rawMinRttMs = (m_rawMinRttMs == 0) ? lastMs : std::min(m_rawMinRttMs, lastMs);
    }

    Time now = Simulator::Now();
    if (m_lastEval.IsZero())
    {
        m_lastEval = now;
        return;
    }
    if (now - m_lastEval >= m_interval)
    {
        Evaluate(tcb);
    }
}

void
TcpPredictive::Evaluate(Ptr<TcpSocketState> tcb)
{
    Time now = Simulator::Now();
    double nowS = now.GetSeconds();
    double elapsed = (now - m_lastEval).GetSeconds();

    while (!m_lossTimes.empty() && m_lossTimes.front() < nowS - 2.0)
    {
        m_lossTimes.pop_front();
    }
    double lossRecent = std::count_if(m_lossTimes.begin(), m_lossTimes.end(),
                                      [nowS](double t) { return t >= nowS - 0.5; });
    double loss2s = m_lossTimes.size();

    uint32_t cwnd = tcb->m_cWnd;
    m_cwndHistory.push_back(cwnd);
    if (m_cwndHistory.size() > 20) // 2 s of 100 ms samples
    {
        m_cwndHistory.pop_front();
    }
    uint32_t cwndMax = *std::max_element(m_cwndHistory.begin(), m_cwndHistory.end());

    bool useMin = m_minRttSignal && m_intervalMinRttMs > 0 && m_rawMinRttMs > 0;
    double sigMs = useMin ? m_intervalMinRttMs : m_srttMs;  // RTT signal for the model
    double baseMs = useMin ? m_rawMinRttMs : m_minRttMs;     // base RTT for the model
    if (sigMs > 0 && baseMs > 0)
    {
        double cwndSeg = static_cast<double>(cwnd) / tcb->m_segmentSize;
        double rttRatio = sigMs / baseMs;
        double rttGrad = (m_prevSrttMs > 0) ? (sigMs - m_prevSrttMs) / baseMs : 0.0;
        double estQueue = std::max(0.0, cwndSeg * (1.0 - baseMs / sigMs));
        double cwndRel = cwndMax > 0 ? static_cast<double>(cwnd) / cwndMax : 1.0;
        double thrMbps = m_ackedBytes * 8.0 / elapsed / 1e6;

        // Queue trend (Phase 6): RTT growth over the last 0.5 s and 1 s, in units of
        // the base RTT, and the RTT relative to its average over the last 1 s
        m_srttHistory.push_back(sigMs);
        if (m_srttHistory.size() > 11) // current sample + 10 previous (1 s)
        {
            m_srttHistory.pop_front();
        }
        size_t n = m_srttHistory.size();
        double rttTrend05 = n > 5 ? (sigMs - m_srttHistory[n - 1 - 5]) / baseMs : 0.0;
        double rttTrend1 = n > 10 ? (sigMs - m_srttHistory[n - 1 - 10]) / baseMs : 0.0;
        size_t avgCount = std::min<size_t>(n, 10);
        double rttAvg =
            std::accumulate(m_srttHistory.end() - avgCount, m_srttHistory.end(), 0.0) / avgCount;
        double rttVsAvg = sigMs / rttAvg;
        double sinceLoss = m_lastLossTime < 0 ? 10.0 : std::min(10.0, nowS - m_lastLossTime);

        m_prediction = predictive::PredictCongestion(rttRatio, rttGrad, estQueue, cwndSeg, cwndRel,
                                                     thrMbps, lossRecent, loss2s, rttTrend05,
                                                     rttTrend1, rttVsAvg, sinceLoss);

        // Competition detector: lowest RTT of each interval over the last
        // CompetitionWindow; if even that stays above the threshold, the queue never
        // drained, so a loss-based sender is assumed and Predictive acts like Reno
        if (m_compWindow.IsStrictlyPositive())
        {
            if (m_intervalMinRttMs > 0)
            {
                m_rttFloorHistory.push_back(m_intervalMinRttMs);
            }
            auto needed = static_cast<size_t>(std::round(m_compWindow.GetSeconds() / m_interval.GetSeconds()));
            while (m_rttFloorHistory.size() > needed)
            {
                m_rttFloorHistory.pop_front();
            }
            if (m_rttFloorHistory.size() == needed)
            {
                double floorMs = *std::min_element(m_rttFloorHistory.begin(), m_rttFloorHistory.end());
                double detectorBaseMs =
                    (m_detectorRawBase && m_rawMinRttMs > 0) ? m_rawMinRttMs : m_minRttMs;
                if (floorMs / detectorBaseMs > m_compThreshold)
                {
                    m_lastCompEvidence = now;
                }
                m_competitive = now - m_lastCompEvidence <= m_compHold;
            }
        }
        s_evaluations++;
        s_competitiveEvaluations += m_competitive ? 1 : 0;

        // React before the queue overflows: shrink the window at most once per RTT,
        // and only while TCP is not already handling a loss.
        bool canReduce = !m_competitive && tcb->m_congState == TcpSocketState::CA_OPEN &&
                         now - m_lastReduction >= MilliSeconds(static_cast<int64_t>(m_srttMs));
        if (m_prediction == predictive::HIGH && canReduce)
        {
            uint32_t reduced = std::max<uint32_t>(static_cast<uint32_t>(cwnd * m_beta),
                                                  m_minWindow * tcb->m_segmentSize);
            if (reduced < cwnd)
            {
                tcb->m_cWnd = reduced;
                tcb->m_cWndInfl = reduced;
                tcb->m_ssThresh = reduced; // leave slow start
                m_lastReduction = now;
                s_proactiveReductions++;
            }
        }
        m_prevSrttMs = sigMs;
    }
    m_ackedBytes = 0;
    m_intervalMinRttMs = 0;
    m_lastEval = now;
}

void
TcpPredictive::IncreaseWindow(Ptr<TcpSocketState> tcb, uint32_t segmentsAcked)
{
    if (m_competitive || tcb->m_cWnd < m_minWindow * tcb->m_segmentSize)
    {
        // Competitor present, or window too small to matter: grow like Reno
        TcpLinuxReno::IncreaseWindow(tcb, segmentsAcked);
        return;
    }
    if (m_prediction == predictive::HIGH)
    {
        return; // reduced in Evaluate(); no growth until the prediction clears
    }
    if (m_prediction == predictive::MEDIUM && m_holdOnMedium)
    {
        // Grow at a fraction of Reno's rate: ACKs are converted to growth credit
        m_ackCredit += segmentsAcked * m_mediumGrowth;
        auto credited = static_cast<uint32_t>(m_ackCredit);
        m_ackCredit -= credited;
        if (credited > 0)
        {
            TcpLinuxReno::IncreaseWindow(tcb, credited);
        }
        return;
    }
    TcpLinuxReno::IncreaseWindow(tcb, segmentsAcked);
}

Ptr<TcpCongestionOps>
TcpPredictive::Fork()
{
    return CopyObject<TcpPredictive>(this);
}

} // namespace ns3
