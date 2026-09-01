import type { Metadata } from "next";

import { color, font } from "./design/tokens";

export const metadata: Metadata = {
  title: "シルバー人材センター お仕事案内",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ja">
      <body
        style={{
          fontFamily: font.family,
          margin: 0,
          padding: 0,
          background: color.bg,
          color: color.text,
        }}
      >
        {children}
      </body>
    </html>
  );
}
