export type DevPersonaId = "merchant" | "analyst" | "alt-merchant";
export type ConsoleRole = "merchant" | "analyst" | "admin";

export interface DevHeaders {
  "X-Dev-Role": string;
  "X-Dev-Merchant-Id": string;
  "X-Dev-User-Id": string;
}

export interface AuthSession {
  token: string;
  label: string;
  role: ConsoleRole;
  merchantId: string;
  developmentOnly: boolean;
  devHeaders: DevHeaders;
}

export interface DevPersona {
  id: DevPersonaId;
  label: string;
  description: string;
  token: string;
  role: ConsoleRole;
  devHeaders: DevHeaders;
}

export const SESSION_STORAGE_KEY = "identitytwin.console.session.v1";

export const DEV_MERCHANT_ID = "00000000-0000-0000-0000-000000000001";
export const DEV_ANALYST_ID = "00000000-0000-0000-0000-000000000002";
export const DEV_ALT_MERCHANT_ID = "00000000-0000-0000-0000-000000000099";
export const DEV_MERCHANT_USER_ID = "11111111-1111-1111-1111-111111111111";

export const DEV_PERSONAS: DevPersona[] = [
  {
    id: "merchant",
    label: "Merchant operator",
    description: "Merchant-scoped operator. Incident approval stays server-denied.",
    token: "dev-merchant-token",
    role: "merchant",
    devHeaders: {
      "X-Dev-Role": "merchant",
      "X-Dev-Merchant-Id": DEV_MERCHANT_ID,
      "X-Dev-User-Id": DEV_MERCHANT_USER_ID,
    },
  },
  {
    id: "analyst",
    label: "Risk analyst",
    description: "Analyst scope for reviewing, approving and resolving incidents.",
    token: "dev-analyst-token",
    role: "analyst",
    devHeaders: {
      "X-Dev-Role": "analyst",
      "X-Dev-Merchant-Id": DEV_MERCHANT_ID,
      "X-Dev-User-Id": DEV_ANALYST_ID,
    },
  },
  {
    id: "alt-merchant",
    label: "Other merchant",
    description: "Second tenant used to verify merchant-scope isolation.",
    token: "dev-other-merchant-token",
    role: "merchant",
    devHeaders: {
      "X-Dev-Role": "merchant",
      "X-Dev-Merchant-Id": DEV_ALT_MERCHANT_ID,
      "X-Dev-User-Id": DEV_MERCHANT_USER_ID,
    },
  },
];