import type { CSSProperties } from "react";

type Capture = {
  file: string;
  caption: string;
  size: [number, number];
  crop?: [number, number, number, number];
};
const lookup: Capture = {
  file: "lookup-frequency-pitch.png", size: [1266, 768], crop: [810, 140, 345, 320],
  caption: "A real lookup for 論文: web buttons beside the term, JPDB frequency beside the dictionary, and the Kanjium pitch graph above the definitions.",
};
const web: Capture = {
  file: "web-lookup-settings.png", size: [820, 728],
  caption: "Settings → Web Lookup. Enable the buttons, choose each source's language and voice, then save. Refresh loads newly imported sources.",
};
const general: Capture = {
  file: "general-settings.png", size: [820, 728], crop: [32, 282, 753, 354],
  caption: "Settings → General. Choose the popup theme and pitch style, or enable Hook + Shift. Save Language Settings applies these choices.",
};
const captures: Record<string, Capture[]> = {
  "google-images": [{file:"google-images-result.png",size:[960,748],caption:"IMG opens Google Images for the selected term inside Anki. Results vary by language and availability."}, web],
  "youglish": [{file:"youglish-result.png",size:[960,748],caption:"YG opens YouGlish with the selected word and language. The matching word is highlighted in the example transcript."}, web],
  "audio": [{...lookup,caption:"Click the speaker beside 論文 to request Google audio. YG and IMG are separate actions."},web],
  "frequency": [{...lookup,caption:"JPDBv2 reports 10330 for 論文 in this installed dictionary. Frequency values stay beside the dictionary heading, leaving room for definitions."}],
  "pitch-accent": [{...lookup,caption:"Kanjium provides the ろんぶん [0] graph for this reading. The source name appears below the graph."},general],
  "custom-css": [{file:"custom-css-preview.png",size:[760,708],caption:"Insert Example adds editable starter CSS. Preview uses a sample entry so you can inspect the result before saving."}],
  "themes": [general,{...lookup,caption:"The popup uses the selected theme for its term, reading, source labels and metadata. This screenshot shows the active light palette."}],
  "hook-shift": [{...general,caption:"Enable Hook + Shift mode in General and save. Then position the pointer over card text and hold Shift."}],
  "nested-popups": [{file:"nested-result.png",size:[1266,768],crop:[580,125,580,568],caption:"Selecting “thesis” inside the 論文 definition opens a second popup while the original lookup stays visible."},{file:"nested-settings.png",size:[820,728],crop:[32,282,753,354],caption:"Set Popup lookup behavior to Open nested popup, then save. The trigger-key setting still applies to text selection."}],
};

export default function GuideMedia({ slug }: { slug: string }) {
  return <div className="guide-captures">
    {captures[slug]?.map((capture, index) => {
      const [iw, ih] = capture.size;
      const [x,y,w,h] = capture.crop || [0,0,iw,ih];
      const src = `../../guide-captures/${capture.file}`;
      const style: CSSProperties = {width:`${iw/w*100}%`, height:`${ih/h*100}%`, left:`${-x/w*100}%`, top:`${-y/h*100}%`};
      return <figure key={capture.file}>
        <a className="capture-focus" href={src} target="_blank" rel="noreferrer" style={{aspectRatio:`${w} / ${h}`, maxWidth: Math.min(760, w * 1.5)}} aria-label={`Open full screenshot: ${capture.caption}`}>
          <img src={src} alt={capture.caption} style={style} loading={index === 0 ? "eager" : "lazy"} />
        </a>
        <figcaption><span className="capture-number">{index + 1}</span>{capture.caption}</figcaption>
      </figure>;
    })}
  </div>;
}
