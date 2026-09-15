import Link from "next/link";
import { guides } from "../guides-data";
import FeatureIcon from "./feature-icon";

export const metadata = { title: "Feature guides | YomiLens" };

export default function Guides() {
  return <>
    <h1>Feature guides</h1>
    <div className="feature-tiles">
      {guides.map(({ id, title }, index) => <Link className={`feature-tile tone-${index % 4}`} href={`/guides/${id}/`} key={id}>
        <span className="feature-icon"><FeatureIcon id={id} /></span>
        <h2>{title}</h2>
      </Link>)}
    </div>
  </>;
}
