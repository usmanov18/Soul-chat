/**
 * Presentational components.
 *
 * These are the pieces the dashboard is built from, so the tests pin the
 * contracts the pages rely on: what renders, what is omitted when absent, and —
 * for StatusChip — that *every* backend topic status has a tone. A status with
 * no tone renders an unstyled chip, which is how a new backend state silently
 * ends up invisible in the admin panel.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EmptyState, Panel, StatCard, StatusChip } from "./cards";

/** Mirrors backend `app/enums.py::TopicStatus`. */
const TOPIC_STATUSES = [
  "draft",
  "active",
  "frozen",
  "blocked",
  "delete_pending",
  "archived",
  "deleted",
] as const;

describe("StatCard", () => {
  it("renders the label and value", () => {
    render(<StatCard label="Jami foydalanuvchi" value={128} />);
    expect(screen.getByText("Jami foydalanuvchi")).toBeTruthy();
    expect(screen.getByText("128")).toBeTruthy();
  });

  it("renders a numeric zero rather than dropping it", () => {
    render(<StatCard label="Bugungi xabarlar" value={0} />);
    expect(screen.getByText("0")).toBeTruthy();
  });

  it("omits the hint node when no hint is given", () => {
    const { container } = render(<StatCard label="A" value={1} />);
    expect(container.querySelector(".text-slate-400")).toBeNull();
  });

  it("renders the hint when provided", () => {
    render(<StatCard label="A" value={1} hint="+12 bu hafta" />);
    expect(screen.getByText("+12 bu hafta")).toBeTruthy();
  });
});

describe("Panel", () => {
  it("renders title, subtitle, children and the action slot", () => {
    render(
      <Panel title="Suhbatlar" subtitle="24 ta faol" action={<button>Barchasi</button>}>
        <p>ichidagi jadval</p>
      </Panel>
    );
    expect(screen.getByText("Suhbatlar")).toBeTruthy();
    expect(screen.getByText("24 ta faol")).toBeTruthy();
    expect(screen.getByText("ichidagi jadval")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Barchasi" })).toBeTruthy();
  });

  it("omits the subtitle paragraph when absent", () => {
    const { container } = render(
      <Panel title="Faqat sarlavha">
        <span />
      </Panel>
    );
    expect(container.querySelector(".text-slate-400")).toBeNull();
  });
});

describe("StatusChip", () => {
  it("replaces the underscore with a space", () => {
    render(<StatusChip status="delete_pending" />);
    expect(screen.getByText("delete pending")).toBeTruthy();
  });

  it.each(TOPIC_STATUSES)("gives %s a tone", (status) => {
    const { container } = render(<StatusChip status={status} />);
    const chip = container.querySelector(".chip");
    expect(chip).not.toBeNull();
    // no tone means the class list is just "chip"
    expect(chip!.className.trim()).not.toBe("chip");
  });

  it("keeps distinct tones distinct", () => {
    const tones = TOPIC_STATUSES.map((status) => {
      const { container } = render(<StatusChip status={status} />);
      return container.querySelector(".chip")!.className;
    });
    expect(new Set(tones).size).toBe(TOPIC_STATUSES.length);
  });

  it("does not crash on an unknown status and still humanises it", () => {
    render(<StatusChip status="something_new" />);
    expect(screen.getByText("something new")).toBeTruthy();
  });

  it("replaces every underscore, not just the first", () => {
    render(<StatusChip status="a_b_c" />);
    expect(screen.getByText("a b c")).toBeTruthy();
  });
});

describe("EmptyState", () => {
  it("renders the message", () => {
    render(<EmptyState message="Hech narsa topilmadi" />);
    expect(screen.getByText("Hech narsa topilmadi")).toBeTruthy();
  });
});