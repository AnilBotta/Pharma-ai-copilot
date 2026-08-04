"use client";

import { motion, type Variants } from "framer-motion";
import { cn } from "@/lib/utils";

export const EASE = [0.22, 1, 0.36, 1] as const;

export const fadeUp: Variants = {
  hidden: { opacity: 0, y: 16 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.5, ease: EASE },
  },
};

export const fadeIn: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { duration: 0.45, ease: EASE } },
};

export const scaleIn: Variants = {
  hidden: { opacity: 0, scale: 0.96 },
  visible: {
    opacity: 1,
    scale: 1,
    transition: { duration: 0.4, ease: EASE },
  },
};

export const stagger = (staggerChildren = 0.07, delayChildren = 0.05): Variants => ({
  hidden: {},
  visible: { transition: { staggerChildren, delayChildren } },
});

export function FadeUp({
  children,
  className,
  delay = 0,
  once = true,
  ...rest
}: React.ComponentProps<typeof motion.div> & { delay?: number; once?: boolean }) {
  return (
    <motion.div
      initial="hidden"
      whileInView="visible"
      viewport={{ once, margin: "-40px" }}
      variants={{
        hidden: fadeUp.hidden,
        visible: {
          ...fadeUp.visible,
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
}: React.ComponentProps<typeof motion.div> & {
  staggerChildren?: number;
  delayChildren?: number;
}) {
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
