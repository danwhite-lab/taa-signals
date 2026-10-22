import { expect, it } from "vitest";
import { readFileSync } from "node:fs";

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

it("preserves the original 512 and Apple images byte for byte", () => {
  for (const name of ["taa-signals-icon-512.png", "apple-touch-icon.png"])
    expect(readFileSync(`./public/${name}`)).toEqual(readFileSync(`../static/${name}`));
  expect(pngSize("./public/apple-touch-icon.png")).toBe("180x180");
});

it("links the manifest and Apple touch icon through the root metadata", () => {
  const layout = readFileSync("./app/layout.tsx", "utf8");
  expect(layout).toContain('manifest: "/manifest.webmanifest"');
  expect(layout).toContain('apple: [{ url: "/apple-touch-icon.png", sizes: "180x180", type: "image/png" }]');
  expect(layout).toContain('appleWebApp: { capable: true, title: "Signalboard"');
  expect(layout).toContain("<TopNavigation />");
  expect(layout).toContain("<AuthGate>{children}</AuthGate>");
});
