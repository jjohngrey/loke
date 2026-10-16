import type { Metadata } from "next";
import { Plus_Jakarta_Sans } from "next/font/google";
import "katex/dist/katex.min.css";
import "./globals.css";

const plusJakartaSans = Plus_Jakarta_Sans({
  display: "swap",
  subsets: ["latin"],
  variable: "--font-plus-jakarta-sans",
});

export const metadata: Metadata = {
  title: "Loke",
  description:
    "A neuroscience learning workspace with evidence-backed next steps.",
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={plusJakartaSans.variable}
    >
      <body>{children}</body>
    </html>
  );
}
