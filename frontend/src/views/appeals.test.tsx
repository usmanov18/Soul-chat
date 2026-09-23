/**
 * D5: the appeals screen — the operator side of /appeal.
 *
 * The bot half was tested in the backend suite; here the panel half is pinned:
 * a pending appeal can be approved (which must call the decision endpoint with
 * "approve") and the list refreshes; a failure shows up instead of vanishing.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import * as api from "@/lib/api";
import { AppealsView } from "./appeals";

vi.mock("next/navigation", () => ({ usePathname: () => "/panel" }));

const appeal = {
  id: 7,
  tg_id: 111,
  text: "Kechirim, bu xato edi",
  status: "pending",
  decided_at: null,
  decision_note: null,
  created_at: "2026-09-23T10:00:00+00:00",
};

describe("AppealsView", () => {
  it("lists pending appeals with both decision buttons", async () => {
    vi.spyOn(api.endpoints, "appeals").mockResolvedValue([appeal]);
    render(<AppealsView />);
    expect(await screen.findByText("Kechirim, bu xato edi")).toBeTruthy();
    expect(screen.getByText("✅ Banʼni olib tashlash")).toBeTruthy();
    expect(screen.getByText("❌ Rad etish")).toBeTruthy();
  });

  it("sends approve and refreshes the list", async () => {
    const decide = vi
      .spyOn(api.endpoints, "decideAppeal")
      .mockResolvedValue({ id: 7, status: "approved" });
    vi.spyOn(window, "prompt").mockReturnValue("haqiqatan xato");
    const appeals = vi.spyOn(api.endpoints, "appeals").mockResolvedValue([appeal]);

    render(<AppealsView />);
    fireEvent.click(await screen.findByText("✅ Banʼni olib tashlash"));

    await waitFor(() => expect(decide).toHaveBeenCalledWith(7, "approve", "haqiqatan xato"));
    expect(await screen.findByText(/Murojaat #7: approved/)).toBeTruthy();
    await waitFor(() => expect(appeals.mock.calls.length).toBeGreaterThanOrEqual(2));
  });

  it("shows the backend error when the decision is rejected by role", async () => {
    vi.spyOn(api.endpoints, "appeals").mockResolvedValue([appeal]);
    vi.spyOn(api.endpoints, "decideAppeal").mockRejectedValue(
      new api.ApiError(403, "Only admins can lift a ban")
    );
    vi.spyOn(window, "prompt").mockReturnValue("");

    render(<AppealsView />);
    fireEvent.click(await screen.findByText("✅ Banʼni olib tashlash"));
    expect(await screen.findByText(/Only admins can lift a ban/)).toBeTruthy();
  });
});
