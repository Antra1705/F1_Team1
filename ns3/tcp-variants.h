// TCP Tahoe and TCP Reno for NS-3.
//
// NS-3 ships CUBIC and NewReno-style recovery but no Tahoe or classic Reno,
// so they are rebuilt here. Window growth and the loss halving (ssthresh =
// cwnd / 2) come from TcpLinuxReno; the behaviour that distinguishes Tahoe
// from Reno lives in the recovery classes:
//
//   Tahoe: on 3 duplicate ACKs, retransmit and drop cwnd to 1 segment, then
//          slow-start again (no fast recovery).
//   Reno:  on 3 duplicate ACKs, retransmit and set cwnd = ssthresh (fast
//          recovery). A partial ACK means another segment of the same window
//          was lost; classic Reno handles it as a new loss and halves again.
//
// TcpPredictive is the proposed variant: Reno plus a decision tree that
// predicts bottleneck congestion 0.5 s ahead from sender-side measurements
// and reacts before packets are lost. A competition detector switches it to
// plain Reno while a loss-based sender (e.g. CUBIC) keeps the queue full.

#ifndef TCP_VARIANTS_H
#define TCP_VARIANTS_H

#include "ns3/nstime.h"
#include "ns3/tcp-linux-reno.h"
#include "ns3/tcp-recovery-ops.h"

#include <deque>

namespace ns3
{

class TcpTahoe : public TcpLinuxReno
{
  public:
    static TypeId GetTypeId();
    TcpTahoe();
    TcpTahoe(const TcpTahoe& sock);
    std::string GetName() const override;
    Ptr<TcpCongestionOps> Fork() override;
};

class TcpReno : public TcpLinuxReno
{
  public:
    static TypeId GetTypeId();
    TcpReno();
    TcpReno(const TcpReno& sock);
    std::string GetName() const override;
    Ptr<TcpCongestionOps> Fork() override;
};

class TcpTahoeRecovery : public TcpRecoveryOps
{
  public:
    static TypeId GetTypeId();
    TcpTahoeRecovery();
    TcpTahoeRecovery(const TcpTahoeRecovery& recovery);
    std::string GetName() const override;
    void EnterRecovery(Ptr<TcpSocketState> tcb,
                       uint32_t dupAckCount,
                       uint32_t unAckDataCount,
                       uint32_t deliveredBytes) override;
    void DoRecovery(Ptr<TcpSocketState> tcb, uint32_t deliveredBytes, bool isDupAck) override;
    void ExitRecovery(Ptr<TcpSocketState> tcb) override;
    Ptr<TcpRecoveryOps> Fork() override;
};

class TcpRenoRecovery : public TcpRecoveryOps
{
  public:
    static TypeId GetTypeId();
    TcpRenoRecovery();
    TcpRenoRecovery(const TcpRenoRecovery& recovery);
    std::string GetName() const override;
    void EnterRecovery(Ptr<TcpSocketState> tcb,
                       uint32_t dupAckCount,
                       uint32_t unAckDataCount,
                       uint32_t deliveredBytes) override;
    void DoRecovery(Ptr<TcpSocketState> tcb, uint32_t deliveredBytes, bool isDupAck) override;
    void ExitRecovery(Ptr<TcpSocketState> tcb) override;
    Ptr<TcpRecoveryOps> Fork() override;
};


class TcpPredictive : public TcpLinuxReno
{
  public:
    static TypeId GetTypeId();
    TcpPredictive();
    TcpPredictive(const TcpPredictive& sock);
    std::string GetName() const override;
    void PktsAcked(Ptr<TcpSocketState> tcb, uint32_t segmentsAcked, const Time& rtt) override;
    void IncreaseWindow(Ptr<TcpSocketState> tcb, uint32_t segmentsAcked) override;
    void CongestionStateSet(Ptr<TcpSocketState> tcb,
                            const TcpSocketState::TcpCongState_t newState) override;
    Ptr<TcpCongestionOps> Fork() override;

    // Proactive (prediction-driven) window reductions across all flows
    static uint64_t GetProactiveReductions();
    static void ResetProactiveReductions();
    // Share of model evaluations (all flows) spent in competitive (Reno) mode, in %
    static double GetCompetitivePercent();

  private:
    void Evaluate(Ptr<TcpSocketState> tcb);

    double m_beta;          //!< Window multiplier on a High prediction
    Time m_interval;        //!< How often the model is evaluated
    bool m_holdOnMedium;    //!< Slow down growth when Medium is predicted
    double m_mediumGrowth;  //!< Fraction of Reno's growth allowed on Medium (0 = freeze)
    double m_ackCredit{0};  //!< Fractional ACK credit carried between calls
    uint32_t m_minWindow;   //!< Below this many segments the predictor never acts
    Time m_compWindow;      //!< Competition detector window (0 = detector off)
    double m_compThreshold; //!< RTT floor / base RTT above which a competitor is assumed
    Time m_compHold;        //!< Stay in competitive mode this long after the last evidence
    bool m_detectorRawBase;  //!< Detector base RTT from raw samples (Phase 10)
    bool m_minRttSignal;     //!< Model features from the per-interval minimum raw RTT (Phase 10)
    double m_rawMinRttMs{0}; //!< Lowest raw RTT sample seen
    Time m_lastCompEvidence{Seconds(-1000)}; //!< When the queue was last seen not draining
    bool m_competitive{false};          //!< Behaving like plain Reno (competitor present)
    double m_intervalMinRttMs{0};       //!< Lowest RTT sample since the last evaluation
    std::deque<double> m_rttFloorHistory; //!< Lowest RTT of each recent interval

    int m_prediction{0};
    Time m_lastEval{Seconds(0)};
    Time m_lastReduction{Seconds(0)};
    uint64_t m_ackedBytes{0};
    double m_srttMs{0};
    double m_prevSrttMs{0};
    double m_minRttMs{0};
    std::deque<uint32_t> m_cwndHistory;
    std::deque<double> m_srttHistory; //!< srtt at the last evaluations (newest last)
    std::deque<double> m_lossTimes;
    double m_lastLossTime{-1};        //!< -1 = no loss yet

    static uint64_t s_proactiveReductions;
    static uint64_t s_evaluations;
    static uint64_t s_competitiveEvaluations;
};

} // namespace ns3

#endif
