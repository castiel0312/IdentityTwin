import type { AuthSession } from "@/lib/auth";
import type { components, operations } from "@/types/api";

export type Schema<K extends keyof components["schemas"]> = components["schemas"][K];

type ListSessionsQuery = NonNullable<
  operations["list_sessions_v1_sessions_get"]["parameters"]["query"]
>;
type ListPayoutsQuery = NonNullable<
  operations["list_merchant_payouts_v1_payouts_get"]["parameters"]["query"]
>;
type ListIncidentsQuery = NonNullable<
  operations["list_incidents_v1_incidents_get"]["parameters"]["query"]
>;
type ListIdentitiesQuery = NonNullable<
  operations["list_merchant_identities_v1_identities_get"]["parameters"]["query"]
>;
type ListAgentsQuery = NonNullable<
  operations["list_merchant_agents_v1_agents_get"]["parameters"]["query"]
>;
type ListAgentAuditQuery = NonNullable<
  operations["list_agent_audit_v1_agents_audit_get"]["parameters"]["query"]
>;
type ListRiskDecisionsQuery = NonNullable<
  operations["list_risk_decisions_v1_risk_decisions_get"]["parameters"]["query"]
>;
type ListEvidenceSealsQuery = NonNullable<
  operations["list_evidence_seals_v1_evidence_seals_get"]["parameters"]["query"]
>;
type ListHoneyWorkspacesQuery = NonNullable<
  operations["list_honey_workspaces_v1_honey_operator_workspaces_get"]["parameters"]["query"]
>;
type OverviewQuery = NonNullable<
  operations["analytics_overview_v1_analytics_overview_get"]["parameters"]["query"]
>;

export interface EvidenceVerification {
  valid: boolean;
  checked: number;
  head_hash: string;
  first_broken_seq?: number | null;
  reason?: string | null;
}

export interface IncidentTimelineItem {
  type: string;
  plane: string;
  trust_level?: string | null;
  summary?: string | null;
  evidence_seq: number;
  evidence_hash: string;
  ts: string;
}

export interface IncidentTimelineResponse {
  incident_id: string;
  timeline: IncidentTimelineItem[];
}

export interface AttackTraceNode {
  id: string;
  type: string;
  label: string;
}

export interface AttackTraceEdge {
  from: string;
  to: string;
  relation: string;
}

export interface IncidentAttackTraceResponse {
  incident_id: string;
  nodes: AttackTraceNode[];
  edges: AttackTraceEdge[];
}

export interface SimulationRunResponse {
  status: string;
  session_id: string;
  incident_sealed: boolean;
  incident_id: string | null;
  evidence_verify?: EvidenceVerification | null;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details?: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details?: Record<string, unknown>) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

interface RequestOptions {
  method?: string;
  query?: object;
  body?: unknown;
  signal?: AbortSignal;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function buildQuery(query?: object): string {
  if (!query) return "";
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const encoded = search.toString();
  return encoded ? `?${encoded}` : "";
}

function errorMessageFromDetail(detail: unknown): string | null {
  if (typeof detail === "string") return detail;
  if (!Array.isArray(detail)) return null;
  for (const entry of detail) {
    if (!isRecord(entry)) continue;
    const message = entry.msg;
    if (typeof message === "string") return message;
  }
  return null;
}

function toApiError(response: Response, payload: unknown): ApiError {
  const body = isRecord(payload) ? payload : {};
  const errorBody = isRecord(body.error) ? body.error : {};
  const code = typeof errorBody.code === "string" ? errorBody.code : `HTTP_${response.status}`;
  const message =
    (typeof errorBody.message === "string" ? errorBody.message : null) ??
    errorMessageFromDetail(body.detail) ??
    response.statusText ??
    `Request failed with status ${response.status}.`;
  const details = isRecord(errorBody.details) ? errorBody.details : undefined;
  return new ApiError(response.status, code, message, details);
}

async function request<T>(
  session: AuthSession,
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = {
    Accept: "application/json",
    Authorization: `Bearer ${session.token}`,
    ...session.devHeaders,
  };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";

  const response = await fetch(`${API_BASE}${path}${buildQuery(options.query)}`, {
    method: options.method ?? "GET",
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
  });

  const text = await response.text();
  let payload: unknown;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }

  if (!response.ok) throw toApiError(response, payload);
  return payload as T;
}

export const api = {
  overview(session: AuthSession, query: OverviewQuery = {}) {
    return request<Schema<"AnalyticsOverviewResponse">>(session, "/v1/analytics/overview", {
      query,
    });
  },

  listSessions(session: AuthSession, query: ListSessionsQuery = {}) {
    return request<Schema<"SessionListResponse">>(session, "/v1/sessions", { query });
  },

  sessionActivity(session: AuthSession, sessionId: string) {
    return request<Schema<"SessionActivityResponse">>(
      session,
      `/v1/sessions/${encodeURIComponent(sessionId)}/activity`,
    );
  },

  createStepUp(session: AuthSession, sessionId: string) {
    return request<Schema<"StepUpChallengeCreateResponse">>(
      session,
      `/v1/sessions/${encodeURIComponent(sessionId)}/step-up`,
      { method: "POST" },
    );
  },

  verifyStepUp(session: AuthSession, sessionId: string, body: Schema<"StepUpVerifyRequest">) {
    return request<Schema<"StepUpVerifyResponse">>(
      session,
      `/v1/sessions/${encodeURIComponent(sessionId)}/step-up/verify`,
      { method: "POST", body },
    );
  },

  listPayouts(session: AuthSession, query: ListPayoutsQuery = {}) {
    return request<Schema<"PayoutListResponse">>(session, "/v1/payouts", { query });
  },

  payout(session: AuthSession, payoutId: string) {
    return request<Schema<"PayoutDetailResponse">>(
      session,
      `/v1/payouts/${encodeURIComponent(payoutId)}`,
    );
  },

  executePayout(session: AuthSession, body: Schema<"PayoutRequest">) {
    return request<Schema<"PayoutResponse">>(session, "/v1/payouts", {
      method: "POST",
      body,
    });
  },

  listIncidents(session: AuthSession, query: ListIncidentsQuery = {}) {
    return request<Schema<"IncidentListResponse">>(session, "/v1/incidents", { query });
  },

  incident(session: AuthSession, incidentId: string) {
    return request<Schema<"IncidentResponse">>(
      session,
      `/v1/incidents/${encodeURIComponent(incidentId)}`,
    );
  },

  incidentActions(session: AuthSession, incidentId: string) {
    return request<Schema<"IncidentActionsResponse">>(
      session,
      `/v1/incidents/${encodeURIComponent(incidentId)}/actions`,
    );
  },

  incidentSeal(session: AuthSession, incidentId: string) {
    return request<Schema<"IncidentSealResponse">>(
      session,
      `/v1/incidents/${encodeURIComponent(incidentId)}/seal`,
    );
  },

  approveIncident(
    session: AuthSession,
    incidentId: string,
    body: Schema<"IncidentActionRequest">,
  ) {
    return request<Schema<"IncidentActionResponse">>(
      session,
      `/v1/incidents/${encodeURIComponent(incidentId)}/approve`,
      { method: "POST", body },
    );
  },

  resolveIncident(
    session: AuthSession,
    incidentId: string,
    body: Schema<"IncidentActionRequest">,
  ) {
    return request<Schema<"IncidentActionResponse">>(
      session,
      `/v1/incidents/${encodeURIComponent(incidentId)}/resolve`,
      { method: "POST", body },
    );
  },

  approveRevocation(
    session: AuthSession,
    incidentId: string,
    body: Schema<"IncidentActionRequest">,
  ) {
    return request<Schema<"IncidentActionResponse">>(
      session,
      `/v1/incidents/${encodeURIComponent(incidentId)}/approve-revocation`,
      { method: "POST", body },
    );
  },

  incidentTimeline(session: AuthSession, incidentId: string) {
    return request<IncidentTimelineResponse>(
      session,
      `/v1/incidents/${encodeURIComponent(incidentId)}/timeline`,
    );
  },

  incidentAttackTrace(session: AuthSession, incidentId: string) {
    return request<IncidentAttackTraceResponse>(
      session,
      `/v1/incidents/${encodeURIComponent(incidentId)}/attack-trace`,
    );
  },

  listIdentities(session: AuthSession, query: ListIdentitiesQuery = {}) {
    return request<Schema<"IdentityListResponse">>(session, "/v1/identities", { query });
  },

  identity(session: AuthSession, identityId: string) {
    return request<Schema<"IdentityDetailResponse">>(
      session,
      `/v1/identities/${encodeURIComponent(identityId)}`,
    );
  },

  runSimulation(session: AuthSession) {
    return request<SimulationRunResponse>(session, "/v1/simulate/attack", {
      method: "POST",
    });
  },

  simulationScenarios(session: AuthSession) {
    return request<Schema<"SimulationScenariosResponse">>(session, "/v1/simulate/scenarios");
  },

  calibration(session: AuthSession) {
    return request<Schema<"CalibrationReportResponse">>(session, "/v1/simulate/calibration");
  },

  agenticPayout(session: AuthSession, body: Schema<"AgenticCommerceRequest">) {
    return request<Schema<"AgenticCommerceResponse">>(session, "/v1/agentic/payouts", {
      method: "POST",
      body,
    });
  },

  listEvidenceSeals(session: AuthSession, query: ListEvidenceSealsQuery = {}) {
    return request<Schema<"EvidenceSealListResponse">>(session, "/v1/evidence/seals", {
      query,
    });
  },

  evidenceSeal(session: AuthSession, sealId: string) {
    return request<Schema<"EvidenceSealDetailResponse">>(
      session,
      `/v1/evidence/seals/${encodeURIComponent(sealId)}`,
    );
  },

  verifyEvidence(session: AuthSession) {
    return request<EvidenceVerification>(session, "/v1/evidence/verify");
  },

  systemContext(session: AuthSession) {
    return request<Schema<"SystemContextResponse">>(session, "/v1/system/context");
  },

  listAgents(session: AuthSession, query: ListAgentsQuery = {}) {
    return request<Schema<"AgentListResponse">>(session, "/v1/agents", { query });
  },

  listAgentAudit(session: AuthSession, query: ListAgentAuditQuery = {}) {
    return request<Schema<"AgentAuditListResponse">>(session, "/v1/agents/audit", {
      query,
    });
  },

  agentErrorCatalog(session: AuthSession) {
    return request<Schema<"AgentErrorCatalogResponse">>(
      session,
      "/v1/agents/authorization-errors",
    );
  },

  agent(session: AuthSession, agentId: string) {
    return request<Schema<"AgentDetailResponse">>(
      session,
      `/v1/agents/${encodeURIComponent(agentId)}`,
    );
  },

  riskConfig(session: AuthSession) {
    return request<Schema<"RiskConfigView">>(session, "/v1/risk/config");
  },

  listRiskDecisions(session: AuthSession, query: ListRiskDecisionsQuery = {}) {
    return request<Schema<"RiskDecisionListResponse">>(session, "/v1/risk/decisions", {
      query,
    });
  },

  riskDecision(session: AuthSession, decisionId: string) {
    return request<Schema<"RiskDecisionDetailResponse">>(
      session,
      `/v1/risk/decisions/${encodeURIComponent(decisionId)}`,
    );
  },

  listHoneyWorkspaces(session: AuthSession, query: ListHoneyWorkspacesQuery = {}) {
    return request<Schema<"HoneyWorkspaceListResponse">>(
      session,
      "/v1/honey/operator/workspaces",
      { query },
    );
  },

  listCanaries(session: AuthSession) {
    return request<Schema<"HoneyCanaryListResponse">>(
      session,
      "/v1/honey/operator/canaries",
    );
  },

  honeyWorkspace(session: AuthSession, sessionId: string) {
    return request<Schema<"HoneyWorkspaceDetailResponse">>(
      session,
      `/v1/honey/operator/workspaces/${encodeURIComponent(sessionId)}`,
    );
  },
};
