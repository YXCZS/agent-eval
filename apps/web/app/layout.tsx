import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Agent Eval Workbench",
  description: "Trace-driven evaluation workspace for prompt, RAG and tool agents",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
