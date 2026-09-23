/**
 * Settings screen — specifically the enforcement metadata (B2).
 *
 * The backend already returned `meta` with an `enforcement` level, but the panel
 * ignored it, so `topic.copy_enabled` looked like any other toggle. That is the
 * bug these tests pin: an operator must be able to tell a guarantee from an
 * advisory note.
 */

import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EnforcementBadge } from "./settings";
import { SettingsView } from "./settings";
import * as api from "@/lib/api";

describe("EnforcementBadge", () => {
  it("labels a real guarantee as enforced", () => {
    render(<EnforcementBadge level="enforced" />);
    expect(screen.getByText("Kafolatlangan")).toBeTruthy();
  });

  it("labels a reactive control distinctly", () => {
    render(<EnforcementBadge level="reactive" />);
    expect(screen.getByText("Keyin bekor qilinadi")).toBeTruthy();
  });

  it("labels an advisory setting as informational only", () => {
    render(<EnforcementBadge level="advisory" />);
    expect(screen.getByText("Faqat ma'lumot")).toBeTruthy();
  });

  it("gives each level a distinct tone", () => {
    const tones = (["enforced", "reactive", "advisory"] as const).map((level) => {
      const { container } = render(<EnforcementBadge level={level} />);
      return container.querySelector(".chip")!.className;
    });
    expect(new Set(tones).size).toBe(3);
  });

  it("falls back to the advisory tone for an unknown level", () => {
    // a future backend value must not crash the panel or look like a guarantee
    render(<EnforcementBadge level={"brand-new" as "advisory"} />);
    expect(screen.getByText("Faqat ma'lumot")).toBeTruthy();
  });
});

describe("SettingsView", () => {
  beforeEach(() => {
    vi.spyOn(api.endpoints, "settings").mockResolvedValue({
      items: { "topic.copy_enabled": true, "topic.forward_enabled": false },
      meta: {
        "topic.copy_enabled": {
          label: "Matnni ko'chirish (copy)",
          enforcement: "advisory",
          note: "Faqat ma'lumot uchun.",
        },
        "topic.forward_enabled": {
          label: "Ko'chirib yuborish (forward)",
          enforcement: "enforced",
          note: "O'chiq bo'lsa rad etiladi.",
        },
      },
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows the human label and the note for each documented setting", async () => {
    render(<SettingsView />);
    expect(await screen.findByText("Matnni ko'chirish (copy)")).toBeTruthy();
    expect(screen.getByText("Faqat ma'lumot uchun.")).toBeTruthy();
    expect(screen.getByText("Ko'chirib yuborish (forward)")).toBeTruthy();
  });

  it("shows the advisory badge next to copy_enabled", async () => {
    render(<SettingsView />);
    await screen.findByText("Matnni ko'chirish (copy)");
    // the key point: the advisory setting is visibly *not* a guarantee
    expect(screen.getByText("Faqat ma'lumot")).toBeTruthy();
    expect(screen.getByText("Kafolatlangan")).toBeTruthy();
  });

  it("still renders a setting the backend has no metadata for", async () => {
    vi.spyOn(api.endpoints, "settings").mockResolvedValue({
      items: { "code.pad": 4 },
      meta: {},
    });
    const { container } = render(<SettingsView />);
    // the raw key is shown twice by design: once as the fallback label and once
    // in the <code> caption. What matters is that the row exists and carries no
    // badge, because the backend said nothing about it.
    await waitFor(() => expect(container.querySelector("code")?.textContent).toBe("code.pad"));
    expect(screen.queryByText("Kafolatlangan")).toBeNull();
    expect(screen.queryByText("Faqat ma'lumot")).toBeNull();
  });

  it("survives an API response without a meta field at all", async () => {
    // older backends only returned { items }
    vi.spyOn(api.endpoints, "settings").mockResolvedValue({ items: { "code.pad": 4 } });
    const { container } = render(<SettingsView />);
    await waitFor(() => expect(container.querySelector("code")?.textContent).toBe("code.pad"));
  });

  it("reports a load failure instead of rendering an empty panel", async () => {
    vi.spyOn(api.endpoints, "settings").mockRejectedValue(new api.ApiError(403, "Ruxsat yo'q"));
    render(<SettingsView />);
    expect(await screen.findByText("Ruxsat yo'q")).toBeTruthy();
  });
});