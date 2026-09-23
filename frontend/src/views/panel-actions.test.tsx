/**
 * Panel actions on users (TZ 22/28), backup verify/download (TZ 31), and the
 * light/dark theme toggle (TZ 34).
 *
 * The backend endpoints existed; the panel could only *look* at problems. The
 * tests pin the operator loop: click an action, reason prompt, state refreshes.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { applyTheme, currentTheme, toggleTheme } from "@/lib/theme";
import * as api from "@/lib/api";
import { BackupView } from "./backup";
import { UsersView } from "./users";

vi.mock("next/navigation", () => ({ usePathname: () => "/panel" }));

const userRow = {
  id: 1,
  tg_id: 111,
  username: "akbar",
  first_name: "Akbar",
  last_name: null,
  gender: "male",
  role: "user",
  is_banned: true,
  is_muted: false,
  warns: 2,
  messages_sent: 10,
  topics_created: 1,
  created_at: "2026-09-23T10:00:00+00:00",
};

describe("UsersView actions", () => {
  beforeEach(() => {
    vi.spyOn(api.endpoints, "users").mockResolvedValue([userRow]);
  });

  it("renders warn/mute/ban/unban buttons for every row", async () => {
    render(<UsersView />);
    expect(await screen.findByText("Akbar")).toBeTruthy();
    expect(screen.getByTitle("⚠️ Ogohlantirish")).toBeTruthy();
    expect(screen.getByTitle("🔇 Mute")).toBeTruthy();
    expect(screen.getByTitle("⛔ Ban")).toBeTruthy();
    expect(screen.getByTitle("✅ Unban")).toBeTruthy();
  });

  it("sends the moderation action with the prompted reason and refreshes", async () => {
    const moderate = vi
      .spyOn(api.endpoints, "moderate")
      .mockResolvedValue({ user_id: 1, warns: 2 });
    const usersSpy = vi.spyOn(api.endpoints, "users").mockResolvedValue([userRow]);
    const prompt = vi.spyOn(window, "prompt").mockReturnValue("apellyatsiya");

    render(<UsersView />);
    fireEvent.click(await screen.findByTitle("✅ Unban"));

    await waitFor(() => expect(moderate).toHaveBeenCalled());
    expect(moderate).toHaveBeenCalledWith({ tg_id: 111, action: "unban", reason: "apellyatsiya" });
    expect(prompt).toHaveBeenCalled();
    // the users list is reloaded after the action
    await waitFor(() => expect(usersSpy.mock.calls.length).toBeGreaterThanOrEqual(2));
    expect(await screen.findByText(/unban/)).toBeTruthy();
  });

  it("surfaces the error when the action fails", async () => {
    vi.spyOn(api.endpoints, "moderate").mockRejectedValue(new api.ApiError(403, "Only admins can ban"));
    vi.spyOn(window, "prompt").mockReturnValue("");

    render(<UsersView />);
    fireEvent.click(await screen.findByTitle("⛔ Ban"));
    expect(await screen.findByText(/Only admins can ban/)).toBeTruthy();
  });
});

describe("BackupView verify + download", () => {
  it("shows the checksum verification result", async () => {
    vi.spyOn(api.endpoints, "backupHistory").mockResolvedValue([
      {
        id: 3,
        target: "local",
        status: "success",
        path: "/backups/dump.sql.gz",
        size: 2048,
        checksum: "abc",
        error: null,
        started_at: "2026-09-23T02:00:00+00:00",
      },
    ]);
    const verify = vi
      .spyOn(api.endpoints, "backupVerify")
      .mockResolvedValue({ id: 3, status: "ok", expected: "abc", actual: "abc" });

    render(<BackupView />);
    fireEvent.click(await screen.findByText("🔍 Tekshirish"));

    await waitFor(() => expect(verify).toHaveBeenCalledWith(3));
    expect(await screen.findByText("ok")).toBeTruthy();
    expect(screen.getByText("⬇️ Yuklab olish")).toBeTruthy();
  });
});

describe("theme", () => {
  it("toggles dark -> light -> dark and persists", () => {
    applyTheme("dark");
    expect(currentTheme()).toBe("dark");
    expect(window.document.documentElement.dataset.theme).toBe("dark");

    expect(toggleTheme()).toBe("light");
    expect(window.localStorage.getItem("soulchat.theme")).toBe("light");
    expect(window.document.documentElement.dataset.theme).toBe("light");

    expect(toggleTheme()).toBe("dark");
    expect(currentTheme()).toBe("dark");
  });
});
