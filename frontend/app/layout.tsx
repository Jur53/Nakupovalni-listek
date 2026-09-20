import type { Metadata } from "next";
import { Geist } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Pametna košarica | Primerjava cen",
  description: "Primerjajte cene živil, razdelite nakup med trgovine in prihranite.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="sl" className={geistSans.variable}>
      <body>{children}</body>
    </html>
  );
}
