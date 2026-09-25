import { AudioLines, BookOpen, ChartNoAxesColumn, Code2, Database, FilePlus2, Image, Maximize2, MousePointer2, Palette, PanelsTopLeft, PenTool, Search, Video, Volume2 } from "lucide-react";

const icons = [Search, FilePlus2, Image, Video, Volume2, ChartNoAxesColumn, AudioLines, Code2, Palette, MousePointer2, PanelsTopLeft, BookOpen, PenTool, Maximize2, Database];
const ids = ["popup-lookup", "anki-export", "google-images", "youglish", "audio", "frequency", "pitch-accent", "custom-css", "themes", "hook-shift", "nested-popups", "kanji-tab", "hanzi-writer", "popup-resize", "add-to-db"];

export default function FeatureIcon({ id }: { id: string }) {
  const Icon = icons[ids.indexOf(id)] || Code2;
  return <Icon size={32} strokeWidth={1.6} aria-hidden="true" />;
}
