import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Agent Eval 评测工作台",
  description: "面向 Prompt、RAG 和 Tool Agent 的 Trace 评测工作台",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
