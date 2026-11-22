import { expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";

const manifest = JSON.parse(readFileSync("./public/manifest.webmanifest", "utf8"));
const pngSize = (path: string) => {
  const png = readFileSync(path);
  expect(png.subarray(0, 8)).toEqual(Buffer.from([137,80,78,71,13,10,26,10]));
  expect(png.toString("ascii", 12, 16)).toBe("IHDR");
  return `${png.readUInt32BE(16)}x${png.readUInt32BE(20)}`;
};

it("provides a standalone root-scoped TAA Signals manifest with a theme colour", () => {
  expect(manifest).toMatchObject({ id:"/", name:"TAA Signals", short_name:"TAA Signals", start_url:"/", scope:"/", display:"standalone" });
  expect(manifest.theme_color).toBe("#0f2747");
  expect(manifest.background_color).toMatch(/^#[0-9a-f]{6}$/i);
});

it("publishes real 192 and 512 PNGs, including a maskable icon, without old Streamlit paths", () => {
  expect(manifest.icons.map((icon: { sizes: string }) => icon.sizes).sort()).toEqual(["192x192", "512x512"]);
  expect(manifest.icons.some((icon: { purpose: string }) => icon.purpose.split(" ").includes("maskable"))).toBe(true);
  for (const icon of manifest.icons) {
    expect(icon.src).toMatch(/^\/taa-signals-icon-(192|512)\.png$/);
    expect(icon.type).toBe("image/png");
    expect(pngSize(`./public${icon.src}`)).toBe(icon.sizes);
  }
});

it("backs up the old icons byte for byte and publishes the replacement Apple icon", () => {
  for (const name of ["taa-signals-icon-512.png", "apple-touch-icon.png"])
    expect(readFileSync(`./public/icon-backups/2026-11-22/${name}`)).toEqual(readFileSync(`../static/${name}`));
  expect(createHash("sha256").update(readFileSync("./public/icon-backups/2026-11-22/taa-signals-icon-192.png")).digest("hex"))
    .toBe("e2efeeda2cce6b31690b62c13f487f25e0119cd54654ca4d4b45092907a4493c");
  for (const name of ["taa-signals-icon-192.png", "taa-signals-icon-512.png", "apple-touch-icon.png"])
    expect(readFileSync(`./public/${name}`)).not.toEqual(readFileSync(`./public/icon-backups/2026-11-22/${name}`));
  expect(pngSize("./public/apple-touch-icon.png")).toBe("180x180");
});

it("links the manifest and Apple touch icon through the root metadata", () => {
  const layout = readFileSync("./app/layout.tsx", "utf8");
  const favicon = readFileSync("./public/favicon.ico");
  expect(favicon.readUInt16LE(0)).toBe(0);
  expect(favicon.readUInt16LE(2)).toBe(1);
  expect(favicon.readUInt16LE(4)).toBe(4);
  expect(Array.from({length:4}, (_, index) => favicon[6 + index * 16]).sort((a,b)=>a-b)).toEqual([16,32,48,64]);
  expect(layout).toContain('url: "/favicon.ico"');
  expect(layout).toContain('manifest: "/manifest.webmanifest"');
  expect(layout).toContain('apple: [{ url: "/apple-touch-icon.png", sizes: "180x180", type: "image/png" }]');
  expect(layout).toContain('appleWebApp: { capable: true, title: "Signalboard"');
  expect(layout).toContain("<TopNavigation />");
  expect(layout).toContain("<AuthGate>{children}</AuthGate>");
});
