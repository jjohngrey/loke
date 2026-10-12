import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "Loke | Learning partner",
  description:
    "A neuroscience learning workspace with evidence-backed next steps.",
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
