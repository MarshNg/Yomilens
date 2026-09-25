import type { CSSProperties } from "react";

type Capture = {
  file: string;
  caption: string;
  size: [number, number];
  crop?: [number, number, number, number];
};

const webToggles: Capture = {
  file: "web-lookup-toggle-settings.png",
  size: [1644, 404],
  caption: "Settings -> Web Lookup. Enable the speaker, automatic speech, YouGlish, and Google Images buttons, then refresh dictionary sources when needed.",
};

const webSources: Capture = {
  file: "web-lookup-source-settings.png",
  size: [1558, 932],
  caption: "Assign a YouGlish language, Google language, and audio voice to each dictionary source, then save the Web Lookup settings.",
};

const captures: Record<string, Capture[]> = {
  "popup-lookup": [
    {
      file: "yomilens-demo.gif",
      size: [900, 563],
      caption: "Select text on an Anki card to open YomiLens, explore the result, and continue reviewing without leaving Anki.",
    },
  ],
  "anki-export": [
    {
      file: "anki-export.png",
      size: [1640, 1468],
      caption: "Choose a deck and note type, map YomiLens values to Anki fields, then save before using the star button in a popup.",
    },
  ],
  "google-images": [
    {
      file: "google-images.png",
      size: [1924, 1506],
      caption: "IMG opens Google Images for the lookup term using the language assigned to that dictionary source.",
    },
    webToggles,
    webSources,
  ],
  "youglish": [
    {
      file: "youglish.png",
      size: [1926, 1500],
      caption: "YG opens YouGlish with the selected term and language so you can hear it in real video examples.",
    },
    webToggles,
    webSources,
  ],
  "audio": [
    {
      file: "web-buttons.png",
      size: [768, 228],
      caption: "The speaker sits beside the Anki, YG, and IMG actions in each lookup result.",
    },
    webToggles,
    webSources,
  ],
  "frequency": [
    {
      file: "pitch-frequency.png",
      size: [770, 714],
      caption: "The JPDBv2 frequency badge appears beside the JMdict heading while definitions retain the wider right column.",
    },
  ],
  "pitch-accent": [
    {
      file: "pitch-frequency.png",
      size: [770, 714],
      caption: "A matching Kanjium pitch graph appears above the gloss for the reading shown in the entry.",
    },
    {
      file: "pitch-style-setting.png",
      size: [930, 108],
      caption: "Choose Graph for the full pitch contour or Compact for a smaller notation, then save the General settings.",
    },
  ],
  "custom-css": [
    {
      file: "custom-css.png",
      size: [2082, 1298],
      caption: "Edit CSS on the left and inspect the live dictionary or Kanji preview on the right. Named presets can be loaded, saved, and deleted from the top row.",
    },
  ],
  "themes": [
    {
      file: "theme-setting.png",
      size: [1518, 86],
      caption: "Choose a popup palette in General. The selected theme applies to new lookups after you save.",
    },
  ],
  "hook-shift": [
    {
      file: "trigger-key-setting.png",
      size: [1506, 228],
      caption: "Enable Hook + Shift and choose the key that should trigger lookup while the pointer is over card text.",
    },
  ],
  "nested-popups": [
    {
      file: "nested-popup-result.png",
      size: [1262, 1128],
      caption: "Selecting a word inside one result opens a child lookup while the original popup remains available behind it.",
    },
    {
      file: "nested-popup-setting.png",
      size: [1568, 182],
      caption: "Set Popup lookup behavior to Open nested popup, then save. Reuse current popup keeps lookups in a single window instead.",
    },
  ],
  "kanji-tab": [
    {
      file: "kanji-tab-result.png",
      size: [880, 758],
      caption: "The Kanji tab groups KANJIDIC meanings, on and kun readings, tags, stroke count, grade, JLPT level, frequency, and SKIP data.",
    },
    {
      file: "kanji-tab-setting.png",
      size: [1052, 104],
      caption: "Enable this option to send clicked kanji to the Kanji tab. An installed and enabled KANJIDIC-style dictionary is required.",
    },
  ],
  "hanzi-writer": [
    {
      file: "hanzi-writer-result.png",
      size: [878, 740],
      caption: "The writing tab creates a separate practice tile for each supported character in the lookup term.",
    },
    {
      file: "hanzi-writer-setting.png",
      size: [638, 54],
      caption: "Enable the Hanzi Writer tab in General to add interactive stroke-order practice to the popup.",
    },
  ],
  "popup-resize": [
    {
      file: "popup-resize-result.png",
      size: [1110, 1100],
      caption: "Resize the popup by dragging its edge. YomiLens remembers the new dimensions for later lookups.",
    },
    {
      file: "popup-resize-setting.png",
      size: [1522, 100],
      caption: "Set an exact default width and height, or reset the popup size from General settings.",
    },
  ],
  "add-to-db": [
    {
      file: "add-to-db.png",
      size: [1036, 1066],
      caption: "Add or edit the word, reading, and one-definition-per-line glosses, then save the entry to an existing or newly created dictionary.",
    },
  ],
};

export default function GuideMedia({ slug }: { slug: string }) {
  return <div className="guide-captures">
    {captures[slug]?.map((capture, index) => {
      const [iw, ih] = capture.size;
      const [x, y, w, h] = capture.crop || [0, 0, iw, ih];
      const src = `../../guide-captures/${capture.file}`;
      const style: CSSProperties = {
        width: `${iw / w * 100}%`,
        height: `${ih / h * 100}%`,
        left: `${-x / w * 100}%`,
        top: `${-y / h * 100}%`,
      };
      return <figure key={capture.file}>
        <a
          className="capture-focus"
          href={src}
          target="_blank"
          rel="noreferrer"
          style={{ aspectRatio: `${w} / ${h}`, maxWidth: Math.min(760, w * 1.5) }}
          aria-label={`Open full screenshot: ${capture.caption}`}
        >
          <img src={src} alt={capture.caption} style={style} loading={index === 0 ? "eager" : "lazy"} />
        </a>
        <figcaption><span className="capture-number">{index + 1}</span>{capture.caption}</figcaption>
      </figure>;
    })}
  </div>;
}
