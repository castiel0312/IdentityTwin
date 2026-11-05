import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AppShell } from "@/components/layout/app-shell";
import { useAuth } from "@/lib/auth";
import { AgentAuditPage } from "@/pages/agent-audit";
import { AgentDetailPage } from "@/pages/agent-detail";
import { AgentsPage } from "@/pages/agents";
import { EvidenceDetailPage } from "@/pages/evidence-detail";
import { EvidencePage } from "@/pages/evidence";
import { HoneyDetailPage } from "@/pages/honey-detail";
import { HoneyPage } from "@/pages/honey";
import { IdentityDetailPage } from "@/pages/identity-detail";
import { IncidentDetailPage } from "@/pages/incident-detail";
import { IncidentsPage } from "@/pages/incidents";
import { LoginPage } from "@/pages/login";
import { NotFoundPage } from "@/pages/not-found";
import { OverviewPage } from "@/pages/overview";
import { PayoutDetailPage } from "@/pages/payout-detail";
import { PayoutsPage } from "@/pages/payouts";
import { RiskDecisionPage } from "@/pages/risk-decision";
import { RiskPage } from "@/pages/risk";
import { SessionDetailPage } from "@/pages/session-detail";
import { SessionsPage } from "@/pages/sessions";
import { SimulationPage } from "@/pages/simulation";
import { SystemPage } from "@/pages/system";
import { VaccinationPage } from "@/pages/vaccination";

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useAuth();
  const location = useLocation();
  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: `${location.pathname}${location.search}` }} />;
  }
  return <>{children}</>;
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route index element={<OverviewPage />} />
        <Route path="payouts" element={<PayoutsPage />} />
        <Route path="payouts/:payoutId" element={<PayoutDetailPage />} />
        <Route path="risk" element={<RiskPage />} />
        <Route path="risk/decisions/:decisionId" element={<RiskDecisionPage />} />
        <Route path="incidents" element={<IncidentsPage />} />
        <Route path="incidents/:incidentId" element={<IncidentDetailPage />} />
        <Route path="sessions" element={<SessionsPage />} />
        <Route path="sessions/:sessionId" element={<SessionDetailPage />} />
        <Route path="identities/:userId" element={<IdentityDetailPage />} />
        <Route path="honey" element={<HoneyPage />} />
        <Route path="honey/:sessionId" element={<HoneyDetailPage />} />
        <Route path="evidence" element={<EvidencePage />} />
        <Route path="evidence/:sealId" element={<EvidenceDetailPage />} />
        <Route path="agents" element={<AgentsPage />} />
        <Route path="agents/audit" element={<AgentAuditPage />} />
        <Route path="agents/:agentId" element={<AgentDetailPage />} />
        <Route path="simulation" element={<SimulationPage />} />
        <Route path="system" element={<SystemPage />} />
        <Route path="vaccination" element={<VaccinationPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
