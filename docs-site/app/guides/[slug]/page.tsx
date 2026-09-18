import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { guides } from "../../guides-data";
import FeatureIcon from "../feature-icon";
import GuideMedia from "../guide-media";

export function generateStaticParams() { return guides.map(guide => ({ slug: guide.id })); }
export const dynamicParams = false;

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return { title: `${guides.find(guide => guide.id === slug)?.title || "Guide"} | YomiLens` };
}

export default async function Guide({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const index = guides.findIndex(guide => guide.id === slug);
  if (index < 0) notFound();
  const guide = guides[index];
  const next = guides[(index + 1) % guides.length];
  return <article className="guide-detail">
    <Link className="back-link" href="/guides/"><ArrowLeft size={18} /> All feature guides</Link>
    <div className="guide-title"><FeatureIcon id={guide.id} /><h1>{guide.title}</h1></div>
    <h2>Setup &amp; usage</h2>
    <ol className="guide-steps">{guide.steps.map((step, i) => <li key={step}><span className="step-index" aria-hidden="true">{i + 1}</span><p>{step}</p></li>)}</ol>
    {(slug === "frequency" || slug === "pitch-accent") && <p className="guide-resource"><a href="https://github.com/MarvNC/yomitan-dictionaries">Find Yomitan dictionary sources</a>. Check each source&apos;s license before downloading or redistributing.</p>}
    {slug === "custom-css" && <pre><code>{`/* Enlarge definition text */\n.reading-definitions .g {\n  font-size: 18px;\n  line-height: 1.6;\n}`}</code></pre>}
    <h2 className="capture-heading">In Anki</h2>
    <GuideMedia slug={slug} />
    <footer className="guide-footer"><Link href="/guides/">All guides</Link><Link href={`/guides/${next.id}/`}>{next.title}<ArrowRight size={18} /></Link></footer>
  </article>;
}
