import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PageHeader } from "@/components/common/page-header";
import { RiskMeter } from "@/components/common/risk-meter";

describe("PageHeader", () => {
  it("allows block-level status content without invalid DOM nesting", () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});

    render(
      <PageHeader
        eyebrow="Incident review"
        title="Suspicious payout"
        description={
          <div className="flex flex-wrap items-center gap-2">
            <span>Critical</span>
            <RiskMeter score={96} />
          </div>
        }
      />,
    );

    expect(screen.getByRole("heading", { name: "Suspicious payout" })).toBeInTheDocument();
    expect(screen.getByRole("meter")).toBeInTheDocument();
    const nestingWarnings = consoleError.mock.calls.filter((call) =>
      String(call[0]).toLowerCase().includes("domnesting"),
    );
    expect(nestingWarnings).toEqual([]);
  });
});
