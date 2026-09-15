import Link from "next/link";

export default function GuidesLayout({ children }: { children: React.ReactNode }) {
  return <>
    <header className="toc">
      <Link className="brand" href="/">
        <span className="brand-mark">読</span>
        <span><strong>YomiLens</strong><small>Popup Dictionary Docs</small></span>
      </Link>
      <nav aria-label="Documentation">
        <Link href="/">Documentation</Link>
        <Link href="/guides/">Feature guides</Link>
      </nav>
    </header>
    <main className="guides-page">{children}</main>
  </>;
}
