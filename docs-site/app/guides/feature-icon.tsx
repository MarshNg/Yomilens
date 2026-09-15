import { Image, Volume2, Video, ChartNoAxesColumn, AudioLines, Code2, Palette, MousePointer2, PanelsTopLeft } from "lucide-react";

const icons = [Image, Video, Volume2, ChartNoAxesColumn, AudioLines, Code2, Palette, MousePointer2, PanelsTopLeft];
const ids = ["google-images", "youglish", "audio", "frequency", "pitch-accent", "custom-css", "themes", "hook-shift", "nested-popups"];

export default function FeatureIcon({ id }: { id: string }) {
  const Icon = icons[ids.indexOf(id)] || Code2;
  return <Icon size={32} strokeWidth={1.6} aria-hidden="true" />;
}
