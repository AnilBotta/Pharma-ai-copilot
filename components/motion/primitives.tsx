"use client";

import { motion, useReducedMotion, type Variants } from "framer-motion";
import { cn } from "@/lib/utils";

/**
 * The app's motion vocabulary, in one place.
 *
 * These existed but were imported by nothing, so PageHeader, StatCard and
 * EmptyState each carried their own copy of the same ease curve and duration.
 * They are consumed now, and every component here honours
 * `prefers-reduced-motion` — which none of the hand-rolled copies did.
 *
 * The CSS in globals.css already flattens animation *duration* for those
 * users, but Framer animates via inline transforms rather than CSS
 * animations, so it has to be asked separately.
 */
/**
 * Framer's own prop type allows `children` to be a MotionValue, which a plain
 * <div> cannot render. Every component here has a reduced-motion branch that
 * falls back to a <div>, so children are narrowed to ordinary React nodes.
 */
type MotionDivProps = Omit<React.ComponentProps<typeof motion.div>, "children"> & {
  children?: React.ReactNode;
};

export const EASE = [0.22, 1, 0.36, 1] as const;

export const fadeUp: Variants = {
  hidden: { opacity: 0, y: 16 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.5, ease: EASE } },
};

export const fadeIn: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { duration: 0.45, ease: EASE } },
};

export const scaleIn: Variants = {
  hidden: { opacity: 0, scale: 0.96 },
  visible: { opacity: 1, scale: 1, transition: { duration: 0.4, ease: EASE } },
};

export const stagger = (staggerChildren = 0.07, delayChildren = 0.05): Variants => ({
  hidden: {},
  visible: { transition: { staggerChildren, delayChildren } },
});

/**
 * Enters on mount rather than on scroll. This is what a page header wants:
 * `whileInView` on something already in the viewport is a needless bet on
 * intersection-observer timing.
 */
export function Enter({
  children,
  className,
  delay = 0,
  variant = "fadeUp",
  ...rest
}: MotionDivProps & {
  delay?: number;
  variant?: "fadeUp" | "fadeIn" | "scaleIn";
}) {
  const reduce = useReducedMotion();
  const base = { fadeUp, fadeIn, scaleIn }[variant];

  if (reduce) {
    return (
      <div className={className} {...(rest as React.ComponentProps<"div">)}>
        {children}
      </div>
    );
  }

  return (
    <motion.div
      initial="hidden"
      animate="visible"
      variants={{
        hidden: base.hidden,
        visible: {
          ...(base.visible as object),
          transition: { duration: 0.45, ease: EASE, delay },
        },
      }}
      className={className}
      {...rest}
    >
      {children}
    </motion.div>
  );
}

export function FadeUp({
  children,
  className,
  delay = 0,
  once = true,
  ...rest
}: MotionDivProps & { delay?: number; once?: boolean }) {
  const reduce = useReducedMotion();

  if (reduce) {
    return (
      <div className={className} {...(rest as React.ComponentProps<"div">)}>
        {children}
      </div>
    );
  }

  return (
    <motion.div
      initial="hidden"
      whileInView="visible"
      viewport={{ once, margin: "-40px" }}
      variants={{
        hidden: fadeUp.hidden,
        visible: {
          ...(fadeUp.visible as object),
          transition: { duration: 0.5, ease: EASE, delay },
        },
      }}
      className={className}
      {...rest}
    >
      {children}
    </motion.div>
  );
}

export function Stagger({
  children,
  className,
  staggerChildren = 0.07,
  delayChildren = 0,
  ...rest
}: MotionDivProps & {
  staggerChildren?: number;
  delayChildren?: number;
}) {
  const reduce = useReducedMotion();

  if (reduce) {
    return (
      <div className={cn(className)} {...(rest as React.ComponentProps<"div">)}>
        {children}
      </div>
    );
  }

  return (
    <motion.div
      initial="hidden"
      whileInView="visible"
      viewport={{ once: true, margin: "-40px" }}
      variants={stagger(staggerChildren, delayChildren)}
      className={cn(className)}
      {...rest}
    >
      {children}
    </motion.div>
  );
}

export function StaggerItem({
  children,
  className,
  ...rest
}: React.ComponentProps<typeof motion.div>) {
  return (
    <motion.div variants={fadeUp} className={className} {...rest}>
      {children}
    </motion.div>
  );
}
