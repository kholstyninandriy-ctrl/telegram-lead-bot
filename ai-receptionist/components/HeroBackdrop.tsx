"use client";

import { useEffect, useRef } from "react";

/** Cursor at the far right, and at the far left. */
const MIN_SCALE = 1.0;
const MAX_SCALE = 1.35;

/**
 * The hero photo, zooming with the pointer: left pulls the view in, right
 * pushes it back out.
 *
 * The scale eases toward the pointer rather than snapping to it, and the
 * animation frame stops once it has caught up, so an idle page costs nothing.
 * Touch devices and anyone who asked for reduced motion get a still image.
 */
export default function HeroBackdrop() {
  const imageRef = useRef<HTMLImageElement>(null);

  useEffect(() => {
    const image = imageRef.current;
    if (!image) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    if (!window.matchMedia("(pointer: fine)").matches) return;

    let target = 0.5;
    let current = 0.5;
    let frame = 0;

    const draw = () => {
      current += (target - current) * 0.07;
      image.style.transform = `scale(${(MAX_SCALE - (MAX_SCALE - MIN_SCALE) * current).toFixed(4)})`;

      if (Math.abs(target - current) > 0.0005) {
        frame = requestAnimationFrame(draw);
      } else {
        frame = 0;
      }
    };

    const onPointerMove = (event: PointerEvent) => {
      target = Math.min(1, Math.max(0, event.clientX / window.innerWidth));
      if (!frame) frame = requestAnimationFrame(draw);
    };

    image.style.transform = `scale(${(MAX_SCALE + MIN_SCALE) / 2})`;
    window.addEventListener("pointermove", onPointerMove, { passive: true });

    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);

  return (
    <div className="absolute inset-0 -z-10 overflow-hidden" aria-hidden="true">
      <img
        ref={imageRef}
        src="/images/hero.webp"
        alt=""
        width={2000}
        height={1421}
        fetchPriority="high"
        className="h-full w-full scale-115 object-cover will-change-transform"
        style={{ transitionProperty: "none" }}
      />
      {/* Keeps the glass panel readable however bright the photo is. */}
      <div className="absolute inset-0 bg-slate-900/25" />
    </div>
  );
}
