"use client";

import {
  ArcElement,
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Filler,
  Legend,
  LinearScale,
  LineElement,
  PointElement,
  Tooltip,
} from "chart.js";
import { Bar, Doughnut, Line } from "react-chartjs-2";

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  ArcElement,
  Filler,
  Tooltip,
  Legend
);

ChartJS.defaults.color = "#94a3b8";
ChartJS.defaults.borderColor = "rgba(148, 163, 184, 0.15)";
ChartJS.defaults.font.family = "ui-sans-serif, system-ui, sans-serif";

const gradientFill = (ctx: CanvasRenderingContext2D, from: string, to: string) => {
  const gradient = ctx.createLinearGradient(0, 0, 0, 260);
  gradient.addColorStop(0, from);
  gradient.addColorStop(1, to);
  return gradient;
};

export function ActivityChart({ days }: { days: { day: string; messages: number; topics: number }[] }) {
  return (
    <Line
      data={{
        labels: days.map((d) => d.day.slice(5)),
        datasets: [
          {
            label: "Xabarlar",
            data: days.map((d) => d.messages),
            borderColor: "#818cf8",
            tension: 0.35,
            fill: true,
            pointRadius: 0,
            borderWidth: 2,
            backgroundColor: (context) => {
              const chart = context.chart;
              const ctx = chart.ctx;
              return ctx ? gradientFill(ctx, "rgba(129,140,248,0.35)", "rgba(129,140,248,0)") : "#818cf8";
            },
          },
          {
            label: "Yangi suhbatlar",
            data: days.map((d) => d.topics),
            borderColor: "#f472b6",
            tension: 0.35,
            fill: false,
            pointRadius: 0,
            borderWidth: 2,
          },
        ],
      }}
      options={{
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { position: "bottom", labels: { boxWidth: 10 } } },
        scales: { y: { beginAtZero: true, grid: { color: "rgba(148,163,184,0.08)" } } },
      }}
    />
  );
}

export function HoursChart({ hours }: { hours: { hour: number; messages: number }[] }) {
  const buckets = Array.from({ length: 24 }, (_, index) => ({
    hour: index,
    messages: hours.find((h) => h.hour === index)?.messages ?? 0,
  }));
  return (
    <Bar
      data={{
        labels: buckets.map((b) => `${b.hour}`),
        datasets: [
          {
            label: "Xabarlar",
            data: buckets.map((b) => b.messages),
            backgroundColor: "rgba(56,189,248,0.55)",
            borderRadius: 6,
          },
        ],
      }}
      options={{
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: true, grid: { color: "rgba(148,163,184,0.08)" } } },
      }}
    />
  );
}

export function MediaChart({ media }: { media: { kind: string; count: number }[] }) {
  const palette = ["#818cf8", "#f472b6", "#38bdf8", "#34d399", "#fbbf24", "#fb7185"];
  return (
    <Doughnut
      data={{
        labels: media.map((m) => m.kind),
        datasets: [
          {
            data: media.map((m) => m.count),
            backgroundColor: media.map((_, index) => palette[index % palette.length]),
            borderWidth: 0,
          },
        ],
      }}
      options={{
        responsive: true,
        maintainAspectRatio: false,
        cutout: "68%",
        plugins: { legend: { position: "bottom", labels: { boxWidth: 10 } } },
      }}
    />
  );
}

export function WeeklyChart({ weekly }: { weekly: { week: string; messages: number }[] }) {
  return (
    <Bar
      data={{
        labels: weekly.map((w) => w.week),
        datasets: [
          {
            label: "Xabarlar",
            data: weekly.map((w) => w.messages),
            backgroundColor: "rgba(167,139,250,0.55)",
            borderRadius: 6,
          },
        ],
      }}
      options={{
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: true, grid: { color: "rgba(148,163,184,0.08)" } } },
      }}
    />
  );
}
