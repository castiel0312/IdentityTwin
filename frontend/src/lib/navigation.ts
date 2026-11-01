import {
  Activity,
  Bot,
  FileLock2,
  Fingerprint,
  FlaskConical,
  LayoutDashboard,
  Settings,
  Siren,
  Sparkles,
  Wallet,
  type LucideIcon,
} from "lucide-react";

export const NAV_GROUPS = [
  "Monitor",
  "Operations",
  "Intelligence",
  "Containment",
  "Automation",
  "Administration",
] as const;

export type NavGroup = (typeof NAV_GROUPS)[number];

export interface NavItem {
  group: NavGroup;
  to: string;
  label: string;
  description: string;
  icon: LucideIcon;
  end?: boolean;
}

const overviewItem: NavItem = {
  group: "Monitor",
  to: "/",
  label: "Overview",
  description: "Trust overview",
  icon: LayoutDashboard,
  end: true,
};

const payoutsItem: NavItem = {
  group: "Operations",
  to: "/payouts",
  label: "Payouts",
  description: "Payout operations",
  icon: Wallet,
};

const incidentsItem: NavItem = {
  group: "Operations",
  to: "/incidents",
  label: "Incidents",
  description: "Security incidents",
  icon: Siren,
};

const riskItem: NavItem = {
  group: "Intelligence",
  to: "/risk",
  label: "Risk Intelligence",
  description: "Authoritative risk configuration",
  icon: Activity,
};

const sessionsItem: NavItem = {
  group: "Intelligence",
  to: "/sessions",
  label: "Sessions & Identities",
  description: "Sessions & identities",
  icon: Fingerprint,
};

const honeyItem: NavItem = {
  group: "Containment",
  to: "/honey",
  label: "Honey Workspace",
  description: "Honey workspace",
  icon: Sparkles,
};

const evidenceItem: NavItem = {
  group: "Containment",
  to: "/evidence",
  label: "Evidence Vault",
  description: "Tamper-evident evidence",
  icon: FileLock2,
};

const agentsItem: NavItem = {
  group: "Automation",
  to: "/agents",
  label: "Agentic Commerce",
  description: "Agent registry",
  icon: Bot,
};

const simulationItem: NavItem = {
  group: "Automation",
  to: "/simulation",
  label: "Simulation & Calibration",
  description: "Synthetic attack drills",
  icon: FlaskConical,
};

const systemItem: NavItem = {
  group: "Administration",
  to: "/system",
  label: "System & Access",
  description: "Runtime context",
  icon: Settings,
};

export const NAV_ITEMS: NavItem[] = [
  overviewItem,
  payoutsItem,
  incidentsItem,
  riskItem,
  sessionsItem,
  honeyItem,
  evidenceItem,
  agentsItem,
  simulationItem,
  systemItem,
];

export function navItemForPath(pathname: string): NavItem {
  const normalized = pathname.replace(/\/+$/, "") || "/";
  if (normalized === "/") return overviewItem;
  if (normalized === "/agent-audit" || normalized.startsWith("/agent-audit/")) {
    return agentsItem;
  }
  if (normalized === "/identities" || normalized.startsWith("/identities/")) {
    return sessionsItem;
  }
  const candidates = NAV_ITEMS.filter(
    (item) => item.to !== "/" && (normalized === item.to || normalized.startsWith(`${item.to}/`)),
  );
  candidates.sort((left, right) => right.to.length - left.to.length);
  return candidates[0] ?? overviewItem;
}
