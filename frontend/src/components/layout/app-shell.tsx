import { useQuery } from "@tanstack/react-query";
import { ChevronDown, LogOut, Menu, ShieldCheck, UserRound } from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { NAV_GROUPS, NAV_ITEMS, navItemForPath, type NavItem } from "@/lib/navigation";
import { queryClient } from "@/lib/query";
import { truncateMiddle } from "@/lib/format";
import { cn } from "@/lib/utils";

function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex min-w-0 items-center gap-2.5">
      <div className="relative flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-primary/40 bg-primary">
        <span className="font-mono text-[11px] font-bold tracking-tight text-primary-foreground">IT</span>
        <span className="absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full border-2 border-sidebar bg-mint" aria-hidden="true" />
      </div>
      {!compact ? (
        <div className="min-w-0 leading-tight">
          <p className="truncate text-sm font-medium tracking-tight text-foreground">IdentityTwin</p>
          <p className="truncate text-[9px] font-semibold uppercase tracking-[0.18em] text-muted-foreground sm:text-2xs sm:tracking-[0.16em]">
            Trust Operations Console
          </p>
        </div>
      ) : null}
    </div>
  );
}

function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav className="flex-1 min-h-0 space-y-6 overflow-y-auto overflow-x-hidden px-2.5 py-4 scrollbar-thin" aria-label="Primary">
      {NAV_GROUPS.map((group) => {
        const items = NAV_ITEMS.filter((item) => item.group === group);
        if (!items.length) return null;
        return (
          <div key={group}>
            <p className="px-2.5 pb-2 text-[9px] font-semibold uppercase tracking-[0.2em] text-muted-foreground/70 sm:text-2xs">{group}</p>
            <ul className="space-y-0.5">
              {items.map((item) => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    end={item.end}
                    onClick={onNavigate}
                    className={({ isActive }) =>
                      cn(
                        "group relative flex min-w-0 items-center gap-2 rounded-lg px-2.5 py-2 text-[0.8125rem] transition-colors duration-200",
                        isActive
                          ? "bg-white/[0.055] text-foreground"
                          : "text-muted-foreground hover:bg-white/[0.03] hover:text-foreground",
                      )
                    }
                  >
                    {({ isActive }) => (
                      <>
                        <span
                          className={cn(
                            "absolute left-0 top-1/2 h-5 w-[2px] -translate-y-1/2 rounded-full transition-opacity",
                            isActive ? "bg-primary opacity-100" : "opacity-0",
                          )}
                          aria-hidden="true"
                        />
                        <item.icon
                          className={cn(
                            "h-4 w-4 shrink-0 transition-colors",
                            isActive ? "text-primary" : "text-muted-foreground/70 group-hover:text-mint-muted",
                          )}
                          aria-hidden="true"
                        />
                        <span className="min-w-0 truncate">{item.label}</span>
                      </>
                    )}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </nav>
  );
}

function SidebarFooter({
  developmentOnly,
  persona,
  role,
  environment,
}: {
  developmentOnly: boolean;
  persona: string;
  role: string;
  environment: string;
}) {
  return (
    <div className="border-t border-border/70 p-2.5">
      <div className="rounded-xl border border-border/70 bg-white/[0.025] p-2.5">
        <div className="flex items-center justify-between gap-1.5">
          <div className="flex min-w-0 items-center gap-1.5">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-border bg-elevated text-mint">
              <UserRound className="h-3 w-3" aria-hidden="true" />
            </span>
            <p className="min-w-0 truncate text-xs font-medium text-foreground">{persona}</p>
          </div>
          <Badge variant={developmentOnly ? "warning" : "muted"} className="shrink-0 px-1.5 py-0.5 text-[8px] sm:px-2 sm:text-[9px]">
            {developmentOnly ? "DEV" : "LIVE"}
          </Badge>
        </div>
        <p className="mt-1.5 truncate text-[9px] uppercase tracking-[0.12em] text-muted-foreground sm:text-2xs sm:tracking-[0.14em]">
          {role} · {environment || "environment pending"}
        </p>
        <div className="mt-2 flex items-start gap-1.5 border-t border-border/60 pt-2">
          <ShieldCheck className="mt-0.5 h-3 w-3 shrink-0 text-mint-muted" aria-hidden="true" />
          <p className="min-w-0 text-[9px] leading-snug text-muted-foreground sm:text-[10px] sm:leading-relaxed">
            {developmentOnly
              ? "Tab-scoped dev token. Never use in production."
              : "Bearer token held for this tab only."}
          </p>
        </div>
      </div>
    </div>
  );
}

function ApiStatus({
  state,
  detail,
}: {
  state: "checking" | "online" | "offline";
  detail?: string;
}) {
  const tone =
    state === "online"
      ? "bg-signal-normal"
      : state === "offline"
        ? "bg-signal-isolated"
        : "bg-signal-restricted animate-soft-pulse";
  const label = state === "online" ? "API connected" : state === "offline" ? "API unreachable" : "Checking API";
  return (
    <span
      className="hidden items-center gap-2 rounded-full border border-border/70 bg-elevated/60 px-3 py-1.5 text-2xs uppercase tracking-[0.14em] text-muted-foreground md:inline-flex"
      title={detail}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", tone)} aria-hidden="true" />
      {label}
    </span>
  );
}

function AccountMenu() {
  const { session, signOut } = useAuth();
  const navigate = useNavigate();
  if (!session) return null;
  const handleSignOut = () => {
    queryClient.clear();
    signOut();
    navigate("/login", { replace: true });
  };
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" className="h-9 gap-2 px-2 text-left" aria-label="Open account menu">
          <span className="flex h-7 w-7 items-center justify-center rounded-full border border-primary/30 bg-primary/10 text-primary">
            <UserRound className="h-3.5 w-3.5" aria-hidden="true" />
          </span>
          <span className="hidden max-w-40 truncate text-xs font-medium sm:block">{session.label}</span>
          <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuLabel>Signed in</DropdownMenuLabel>
        <div className="px-2.5 pb-2">
          <p className="truncate text-sm font-medium text-foreground">{session.label}</p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Role: <span className="capitalize">{session.role}</span>
            {session.developmentOnly ? " · development only" : ""}
          </p>
        </div>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={handleSignOut}>
          <LogOut className="h-4 w-4" aria-hidden="true" />
          Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function AppShell() {
  const { session } = useAuth();
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();
  const current = navItemForPath(location.pathname);
  const systemQuery = useQuery({
    queryKey: ["system-context"],
    queryFn: () => api.systemContext(session!),
    enabled: Boolean(session),
    staleTime: 30_000,
  });

  const environment = systemQuery.data?.environment;
  const merchant = systemQuery.data?.merchant?.name;
  const developmentOnly = systemQuery.data?.auth.development_only ?? session?.developmentOnly ?? true;
  const mobileTitle: NavItem = current;

  const detailSegment =
    location.pathname !== current.to && location.pathname.startsWith(current.to)
      ? location.pathname.slice(current.to === "/" ? 1 : current.to.length + 1).split("/")[0]
      : null;
  const apiState: "checking" | "online" | "offline" = systemQuery.isError
    ? "offline"
    : systemQuery.isSuccess
      ? "online"
      : "checking";

  return (
    <div className="min-h-screen bg-background">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[100] focus:rounded-full focus:bg-primary focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-primary-foreground"
      >
        Skip to content
      </a>

      <aside className="fixed inset-y-0 left-0 z-40 hidden w-[252px] min-w-0 flex-col border-r border-border/70 bg-sidebar lg:flex">
        <div className="flex h-[72px] items-center gap-3 border-b border-border/70 px-3">
          <Brand />
        </div>
        <NavLinks />
        <SidebarFooter
          developmentOnly={developmentOnly}
          persona={session?.label ?? "Unattributed session"}
          role={session?.role ?? "unknown"}
          environment={environment ?? ""}
        />
      </aside>

      <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
        <SheetContent className="flex w-[min(88vw,280px)] max-w-full flex-col bg-sidebar p-0 text-foreground">
          <div className="flex h-[72px] items-center gap-3 border-b border-border/70 px-3">
            <Brand />
          </div>
          <SheetTitle className="sr-only">Primary navigation</SheetTitle>
          <SheetDescription className="sr-only">Navigate between trust operations modules.</SheetDescription>
          <NavLinks onNavigate={() => setMobileOpen(false)} />
          <SidebarFooter
            developmentOnly={developmentOnly}
            persona={session?.label ?? "Unattributed session"}
            role={session?.role ?? "unknown"}
            environment={environment ?? ""}
          />
        </SheetContent>
      </Sheet>

      <div className="lg:pl-[252px]">
        <header className="sticky top-0 z-30 flex min-h-[72px] items-center justify-between gap-2 border-b border-border/70 bg-background/85 px-3 backdrop-blur-md sm:gap-3 sm:px-4 lg:px-8">
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <Button
              variant="ghost"
              size="icon"
              className="shrink-0 lg:hidden"
              onClick={() => setMobileOpen(true)}
              aria-label="Open navigation"
            >
              <Menu className="h-5 w-5" />
            </Button>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-2xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                <span className="min-w-0 truncate">{mobileTitle.group}</span>
                <span aria-hidden="true">/</span>
                <span className="min-w-0 truncate text-mint-muted">{mobileTitle.label}</span>
                {detailSegment ? (
                  <>
                    <span aria-hidden="true">/</span>
                    <span className="min-w-0 truncate font-mono text-muted-foreground" title={decodeURIComponent(detailSegment)}>
                      {truncateMiddle(decodeURIComponent(detailSegment), 8).toUpperCase()}
                    </span>
                  </>
                ) : null}
              </div>
              <p className="mt-0.5 line-clamp-2 text-sm font-medium leading-snug text-foreground sm:truncate">{mobileTitle.description}</p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1.5 sm:gap-2.5">
            {merchant ? (
              <span className="hidden max-w-40 truncate font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground 2xl:max-w-56 xl:block">
                {merchant}
              </span>
            ) : null}
            <ApiStatus state={apiState} detail={systemQuery.error instanceof Error ? systemQuery.error.message : undefined} />
            <Badge
              variant={environment?.toLowerCase() === "production" ? "danger" : environment ? "warning" : "muted"}
              className="hidden md:inline-flex"
            >
              {environment ? environment.toUpperCase() : "CHECKING"}
            </Badge>
            <AccountMenu />
          </div>
        </header>

        <main id="main-content" className="mx-auto w-full max-w-[1500px] px-4 py-7 lg:px-8 lg:py-10">
          <Outlet />
        </main>

        <footer className="mx-auto flex w-full max-w-[1500px] flex-col gap-1 border-t border-border/60 px-4 py-6 text-[11px] text-muted-foreground lg:px-8">
          <p>IdentityTwin Trust Operations Console · Backend decisions remain authoritative.</p>
          <p>
            {developmentOnly
              ? "Development authentication is active. Synthetic demo data is labelled in each module."
              : "Session credentials are scoped to this browser tab."}
          </p>
        </footer>
      </div>
    </div>
  );
}
