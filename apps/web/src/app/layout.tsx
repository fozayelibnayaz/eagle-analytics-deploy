import type { Metadata, Viewport } from "next";
import Providers from "./providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "Eagle Analytics Hub | Dashboard",
  description: "Unified analytics command center for Eagle3D Streaming.",
  icons: {
    icon: "/favicon.png",
  },
  openGraph: {
    title: "Eagle Analytics Hub",
    description: "Unified analytics command center for Eagle3D Streaming.",
    type: "website",
  },
};

export const viewport: Viewport = {
  themeColor: "#030506",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
