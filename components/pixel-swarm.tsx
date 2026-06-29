"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

interface PixelSwarmProps {
  className?: string;
  /** Spacing between grid cells in px. Lower = denser. */
  gap?: number;
  /** Max dot size in px. */
  dot?: number;
}

/**
 * A field of small white/grey squares arranged on a grid that drift, pulse,
 * and swarm via layered flow noise — evoking a dithered/halftone surface in
 * slow motion. Pure canvas, one RAF loop, and it respects
 * prefers-reduced-motion (renders a still field).
 */
export function PixelSwarm({ className, gap = 14, dot = 5 }: PixelSwarmProps) {
  const canvasRef = React.useRef<HTMLCanvasElement | null>(null);

  React.useEffect(() => {
    const node = canvasRef.current;
    if (!node) return;
    const canvas = node;
    const context = canvas.getContext("2d", { alpha: true });
    if (!context) return;
    const ctx = context;

    const reduced =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    let width = 0;
    let height = 0;
    let dpr = 1;
    let cols = 0;
    let rows = 0;

    function resize() {
      const parent = canvas.parentElement;
      if (!parent) return;
      const rect = parent.getBoundingClientRect();
      width = rect.width;
      height = rect.height;
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      cols = Math.ceil(width / gap) + 1;
      rows = Math.ceil(height / gap) + 1;
    }

    resize();

    // Cheap value-noise-ish flow field built from layered sines. No deps.
    function flow(x: number, y: number, t: number) {
      return (
        Math.sin(x * 0.6 + t) * 0.5 +
        Math.sin(y * 0.7 - t * 0.8) * 0.5 +
        Math.sin((x + y) * 0.35 + t * 0.5) * 0.5
      );
    }

    let raf = 0;
    let start = performance.now();

    function frame(now: number) {
      const t = (now - start) / 1000;
      ctx.clearRect(0, 0, width, height);

      for (let gy = 0; gy < rows; gy++) {
        for (let gx = 0; gx < cols; gx++) {
          const baseX = gx * gap;
          const baseY = gy * gap;

          // Swarm: drift each cell along the flow field.
          const nx = gx * 0.18;
          const ny = gy * 0.18;
          const f1 = flow(nx, ny, t * 0.75);
          const f2 = flow(ny + 5.2, nx - 3.1, t * 0.6);
          const driftX = f1 * gap * 1.7;
          const driftY = f2 * gap * 1.7;

          const px = baseX + driftX;
          const py = baseY + driftY;

          // Brightness pulses with the field so the field "breathes" like
          // the halftone reference — mostly dim greys, occasional whites.
          const wave = (Math.sin(nx + ny + t * 0.9) + f1) * 0.5;
          const intensity = Math.max(0, Math.min(1, 0.42 + wave * 0.55));

          // Shape: dim cells stay small, bright cells swell into bold squares.
          const size = dot * (0.55 + intensity * 1.25);
          const alpha = 0.16 + intensity * 0.72;

          const shade = 150 + Math.floor(intensity * 105); // grey -> white
          ctx.fillStyle = `rgba(${shade}, ${shade}, ${shade}, ${alpha})`;
          const s = size;
          ctx.fillRect(px - s / 2, py - s / 2, s, s);
        }
      }

      if (!reduced) raf = requestAnimationFrame(frame);
    }

    if (reduced) {
      // One static frame.
      frame(start);
    } else {
      raf = requestAnimationFrame(frame);
    }

    window.addEventListener("resize", resize);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
    };
  }, [gap, dot]);

  return (
    <div
      aria-hidden
      className={cn(
        "pointer-events-none absolute inset-0 overflow-hidden",
        className
      )}
    >
      <canvas ref={canvasRef} className="h-full w-full" />
    </div>
  );
}
