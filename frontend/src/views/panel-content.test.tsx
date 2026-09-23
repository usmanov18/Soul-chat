/**
 * Admin panel content views (TZ 28) — media, events, gallery, subscriptions,
 * backup — plus the nav that exposes them.
 *
 * These views were the missing pages: the backend had the tables but the panel
 * could not show them. The tests pin what an operator actually reads: which
 * couple, what kind, whether it reached the channel, and who is missing a
 * mandatory subscription.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Nav, NAV_ITEMS } from "@/components/nav";
import * as api from "@/lib/api";
import { formatBytes, formatDateTime, mediaKindIcon } from "@/lib/format";
import { BackupView } from "./backup";
import { EventsView } from "./events";
import { GalleryView } from "./gallery";
import { MediaView } from "./media";
import { SubscriptionsView } from "./subscriptions";

vi.mock("next/navigation", () => ({ usePathname: () => "/panel" }));

const mediaRow = {
  id: 1,
  topic_code: "A-0042",
  kind: "photo",
  file_id: "fff",
  file_size: 2048,
  width: 800,
  height: 600,
  duration: null,
  mime_type: "image/jpeg",
  caption: "Birinchi rasm",
  published_to_channel: true,
  nsfw: false,
  nsfw_score: 0,
  created_at: "2026-09-23T10:00:00+00:00",
};

describe("MediaView", () => {
  it("renders a media card with code, size and channel mark", async () => {
    vi.spyOn(api.endpoints, "media").mockResolvedValue({ total: 1, items: [mediaRow] });
    render(<MediaView />);
    expect(await screen.findByText("A-0042")).toBeTruthy();
    expect(screen.getByText("Birinchi rasm")).toBeTruthy();
    expect(screen.getByText("2.0 KB")).toBeTruthy();
    expect(screen.getByText("kanalda")).toBeTruthy();
    expect(screen.getByText("800×600")).toBeTruthy();
  });

  it("flags nsfw media with a distinct chip", async () => {
    vi.spyOn(api.endpoints, "media").mockResolvedValue({
      total: 1,
      items: [{ ...mediaRow, nsfw: true, nsfw_score: 88, caption: null }],
    });
    render(<MediaView />);
    expect(await screen.findByText(/nsfw 88/)).toBeTruthy();
  });

  it("shows the empty state when nothing matches", async () => {
    vi.spyOn(api.endpoints, "media").mockResolvedValue({ total: 0, items: [] });
    render(<MediaView />);
    expect(await screen.findByText("Media topilmadi")).toBeTruthy();
  });
});

describe("EventsView", () => {
  it("renders event rows with kind icon and checklist progress", async () => {
    vi.spyOn(api.endpoints, "events").mockResolvedValue({
      total: 1,
      items: [
        {
          id: 1,
          topic_code: "A-0042",
          kind: "checklist",
          title: "Sayohat rejasi",
          description: null,
          due_at: "2026-10-01T18:00:00+00:00",
          remind_at: null,
          location: "Samarqand",
          checklist: ["[x] chipta", "[ ] mehmonxona"],
          status: "scheduled",
          created_at: null,
        },
      ],
    });
    render(<EventsView />);
    expect(await screen.findByText("Sayohat rejasi")).toBeTruthy();
    expect(screen.getByText("1/2")).toBeTruthy();
    expect(screen.getByText("Samarqand")).toBeTruthy();
  });
});

describe("GalleryView", () => {
  it("marks published and failed posts differently", async () => {
    vi.spyOn(api.endpoints, "channelPosts").mockResolvedValue({
      total: 2,
      items: [
        {
          id: 1,
          topic_code: "A-0042",
          kind: "gallery",
          tg_message_id: 5,
          text: "🌸 A-0042",
          template: null,
          media_file_ids: null,
          published_at: "2026-09-23T09:00:00+00:00",
          failed_reason: null,
          created_at: null,
        },
        {
          id: 2,
          topic_code: null,
          kind: "new_topic",
          tg_message_id: null,
          text: "✨ Yangi suhbat",
          template: null,
          media_file_ids: null,
          published_at: null,
          failed_reason: "chat not found",
          created_at: null,
        },
      ],
    });
    render(<GalleryView />);
    expect(await screen.findByText(/xato: chat not found/)).toBeTruthy();
    expect(screen.getByText("chop etildi")).toBeTruthy();
    expect(screen.getByText("✨ Yangi suhbat")).toBeTruthy();
  });
});

describe("SubscriptionsView", () => {
  it("shows who is missing the mandatory membership", async () => {
    vi.spyOn(api.endpoints, "subscriptions").mockResolvedValue({
      total: 2,
      items: [
        {
          tg_id: 111,
          username: "akbar",
          first_name: "Akbar",
          kind: "group",
          chat_id: -100123,
          is_member: true,
          status: "member",
          checked_at: "2026-09-23T08:00:00+00:00",
        },
        {
          tg_id: 222,
          username: null,
          first_name: "Salima",
          kind: "channel",
          chat_id: -100321,
          is_member: false,
          status: "left",
          checked_at: null,
        },
      ],
    });
    render(<SubscriptionsView />);
    expect(await screen.findByText("@akbar")).toBeTruthy();
    expect(screen.getByText("obuna yo'q")).toBeTruthy();
    expect(screen.getByText("a'zo")).toBeTruthy();
  });
});

describe("BackupView", () => {
  it("lists history and reports a successful manual run", async () => {
    const spy = vi
      .spyOn(api.endpoints, "backup")
      .mockResolvedValue({ status: "success", path: "/backups/dump.sql.gz", size: 4096, error: null });
    vi.spyOn(api.endpoints, "backupHistory").mockResolvedValue([
      {
        id: 1,
        target: "local",
        status: "success",
        path: "/backups/old.sql.gz",
        size: 1024,
        checksum: null,
        error: null,
        started_at: "2026-09-23T02:00:00+00:00",
      },
    ]);
    render(<BackupView />);
    expect(await screen.findByText("/backups/old.sql.gz")).toBeTruthy();

    fireEvent.click(screen.getByText("Hozir zaxiralash"));
    await waitFor(() => expect(spy).toHaveBeenCalled());
    expect(await screen.findByText(/Zaxira yaratildi/)).toBeTruthy();
    expect(screen.getByText(/dump\.sql\.gz/)).toBeTruthy();
  });

  it("shows the error when the backup fails", async () => {
    vi.spyOn(api.endpoints, "backup").mockResolvedValue({
      status: "failed",
      path: null,
      size: 0,
      error: null,
    });
    vi.spyOn(api.endpoints, "backupHistory").mockResolvedValue([]);
    render(<BackupView />);
    fireEvent.click(await screen.findByText("Hozir zaxiralash"));
    expect(await screen.findByText(/Zaxira amalga oshmadi/)).toBeTruthy();
  });
});

describe("Nav", () => {
  it("exposes the TZ 28 sections", () => {
    render(<Nav />);
    for (const label of [
      "Media",
      "Eventlar",
      "Galereya",
      "Obunalar",
      "Audit log",
      "Zaxira",
    ]) {
      expect(screen.getByText(label)).toBeTruthy();
    }
    const hrefs = NAV_ITEMS.map((item) => item.href);
    for (const path of [
      "/panel/media",
      "/panel/events",
      "/panel/gallery",
      "/panel/subscriptions",
      "/panel/backup",
    ]) {
      expect(hrefs).toContain(path);
    }
  });
});

describe("format helpers", () => {
  it("formats byte sizes readably", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(500)).toBe("500 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MB");
  });

  it("renders empty dates as a dash", () => {
    expect(formatDateTime(null)).toBe("—");
    expect(formatDateTime("2026-09-23T10:00:00+00:00")).toBe("2026-09-23 10:00:00");
  });

  it("maps every media kind to an icon with a fallback", () => {
    expect(mediaKindIcon("photo")).toBe("📷");
    expect(mediaKindIcon("who-knows")).toBe("📎");
  });
});
