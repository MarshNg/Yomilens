import GuideMenu from "./guide-menu";

const guides = [
  { id: "google-images", title: "Google Images", steps: ["Open Settings → Web Lookup. After installing dictionaries, click Refresh to load their sources.", "Enable Show IMG button. Choose the Google language for each dictionary source, then click Save Web Lookup Settings.", "Look up a word and click IMG to search for images. An internet connection is required."] },
  { id: "youglish", title: "YouGlish", steps: ["In Settings → Web Lookup, enable Show YG button.", "Choose the YouGlish language for each dictionary and save. This setting is separate from the Google language.", "Click YG beside a lookup result to hear the word used in videos. Available examples depend on YouGlish and the selected language."] },
  { id: "audio", title: "Audio", steps: ["In Settings → Web Lookup, enable Show audio button.", "Choose the Google language and Audio voice for each source. Enable Auto speak only if you want automatic playback, then save.", "Click the speaker beside a result to hear Google TTS. Playback requires internet access."] },
  { id: "frequency", title: "Frequency dictionaries", steps: ["Use a build that supports frequency metadata. Download a Yomitan frequency ZIP, such as JPDB, separately from your meaning dictionary.", "Open Settings → Dictionaries and import the ZIP. Keep both the frequency source and your Japanese meaning dictionary enabled, then restart Anki.", "Look up a word. Matching frequency values appear beside the dictionary name. Coverage and ranking depend on the source; no badge can simply mean no matching entry."] },
  { id: "pitch-accent", title: "Pitch accent", steps: ["Use a build that supports pitch metadata. Obtain a Yomitan pitch-accent ZIP, such as Kanjium; a normal JMdict or Jitendex ZIP is not a substitute.", "Import it in Settings → Dictionaries, enable the source and restart Anki.", "In General, choose Pitch accent style: Graph or Compact, then save. Matching pitch information appears above definitions for that reading."] },
  { id: "custom-css", title: "Custom CSS", steps: ["In a build that includes Custom CSS, open Settings → General → Custom CSS.", "Use Insert Example to see YomiLens selectors, then edit the properties you need. It appends a sample without replacing existing CSS.", "Click Preview to inspect the sample, then Save CSS. Open a fresh popup to check real entries. Yomitan CSS is not directly compatible; this field accepts CSS, not JavaScript."] },
  { id: "themes", title: "Themes", steps: ["Open Settings → General and choose a Popup theme.", "Save your General settings and open a new lookup to see the result.", "Choose a dark palette explicitly for a dark popup. Your chosen popup palette stays independent of Anki's light/dark appearance."] },
  { id: "hook-shift", title: "Hook + Shift", steps: ["In Settings → General, enable Hook + Shift mode and the lookup languages you need, then save.", "During review, place your pointer over a word and hold Shift to look it up without selecting it.", "Position the pointer directly over the character you want. Card layout and dictionary coverage can affect matching."] },
  { id: "nested-popups", title: "Nested popups", steps: ["Open Settings → General and select Open nested popup for lookup inside popups, then save.", "Open a lookup, then select a word in its definition to open a child popup.", "The parent stays available so you can return to the original entry. Choose reuse instead if you prefer a single popup."] },
];

const chapters = [
  ["start", "Quick start"],
  ["lookup", "Popup lookup"],
  ["languages", "Languages"],
  ["kanji", "Kanji"],
  ["writer", "Hanzi Writer"],
  ["web", "Web lookup"],
  ["dictionaries", "Dictionaries"],
  ["troubleshooting", "Troubleshooting"],
];

const quickSteps = [
  "Install YomiLens from AnkiWeb.",
  "Open Tools → YomiLens Settings.",
  "Go to Dictionaries and download or import Yomitan/Yomichan ZIP dictionaries.",
  "Restart Anki after dictionary changes.",
  "During review, select text on a card to open the popup.",
];

const features = [
  "Yomitan/Yomichan-compatible dictionary ZIP import",
  "Multi-language lookup with inflection support for many languages",
  "Japanese deinflection and rich structured dictionary entries",
  "KANJIDIC-style kanji lookup in a dedicated Kanji tab",
  "Optional Hanzi Writer stroke-order practice",
  "Nested popup lookup inside existing popup results",
  "Optional Google audio, YouGlish, and Google Images buttons",
  "Profile-safe dictionary storage outside the add-on folder",
];

const troubleshoot = [
  {
    title: "No popup appears",
    text: "Open Settings → General and confirm the language is enabled. If you use a trigger key, hold that key while selecting text.",
  },
  {
    title: "Popup opens but says Not found",
    text: "Install a dictionary for that language, then restart Anki. For Japanese single-kanji lookup, install a KANJIDIC-style dictionary.",
  },
  {
    title: "Web Lookup sources are empty",
    text: "If you just installed dictionaries, open Settings → Web Lookup and click Refresh to load the new dictionary sources.",
  },
  {
    title: "Dictionary changes feel stale",
    text: "After import, download, delete, enable/disable, or re-download, restart Anki before continuing review.",
  },
];

export default function Home() {
  return (
    <main>
      <header className="toc" aria-label="Table of contents">
        <a className="brand" href="#top">
          <span className="brand-mark">読</span>
          <span>
            <strong>YomiLens</strong>
            <small>Popup Dictionary Docs</small>
          </span>
        </a>
        <nav aria-label="Documentation">
          <GuideMenu title="Documentation" items={chapters.map(([id, title]) => ({ id, title }))} />
          <GuideMenu title="Feature guides" items={[{id: "feature-guides", title: "All feature guides"}, ...guides]} />
        </nav>
      </header>

      <div className="page" id="top">
        <header className="hero">
          <p className="eyebrow">Anki add-on guide</p>
          <h1>YomiLens Popup Dictionary</h1>
          <p className="hero-copy">
            A Yomitan/Yomichan-style popup dictionary for Anki review. Select a
            word on a card, look it up instantly, inspect kanji, practice stroke
            order, and keep your dictionary workflow inside Anki.
          </p>
          <div className="hero-actions">
            <a href="https://ankiweb.net/shared/info/1807906393">Install from AnkiWeb</a>
            <a href="https://github.com/MarshNg/yomilens-dictionaries">Dictionary downloads</a>
          </div>
        </header>

        <section id="start" className="section">
          <div className="section-head">
            <p className="section-kicker">01</p>
            <h2>Quick Start</h2>
          </div>
          <div className="steps">
            {quickSteps.map((step, index) => (
              <div className="step" key={step}>
                <span>{index + 1}</span>
                <p>{step}</p>
              </div>
            ))}
          </div>
          <div className="callout">
            <strong>Important:</strong> after changing dictionaries, restart
            Anki before using YomiLens again.
          </div>
        </section>

        <section id="lookup" className="section split">
          <div>
            <div className="section-head">
              <p className="section-kicker">02</p>
              <h2>Popup Lookup During Review</h2>
            </div>
            <p>
              Select text on your Anki card and YomiLens opens a floating
              dictionary popup directly on the review screen. The popup includes
              Search, Kanji, optional Writer, back/forward navigation, nested
              lookup, and configurable web lookup buttons.
            </p>
            <ul className="feature-list">
              {features.slice(0, 4).map((feature) => (
                <li key={feature}>{feature}</li>
              ))}
            </ul>
          </div>
          <figure>
            <img
              src="./screenshots/japanese-deinflection.png"
              alt="Japanese deinflection popup in YomiLens"
            />
            <figcaption>Japanese lookup can resolve inflected forms and show metadata, senses, and examples.</figcaption>
          </figure>
        </section>

        <section id="languages" className="section">
          <div className="section-head">
            <p className="section-kicker">03</p>
            <h2>Language Controls</h2>
          </div>
          <div className="grid two">
            <figure>
              <img
                src="./screenshots/settings-general.png"
                alt="YomiLens language settings"
              />
            </figure>
            <div>
              <p>
                Enable only the languages you want YomiLens to react to. Some
                languages use exact matching, while others use inflection rules
                adapted from the Yomitan ecosystem.
              </p>
              <ul className="feature-list">
                <li>Choose selected languages for popup lookup.</li>
                <li>Set a trigger key such as Shift or Option/Alt.</li>
                <li>Choose whether popup lookup reuses the current popup or opens a nested popup.</li>
                <li>Enable or hide the Hanzi Writer tab.</li>
              </ul>
            </div>
          </div>
        </section>

        <section id="kanji" className="section split">
          <div>
            <div className="section-head">
              <p className="section-kicker">04</p>
              <h2>Kanji Lookup</h2>
            </div>
            <p>
              When a KANJIDIC-style dictionary is installed, YomiLens can show
              kanji meanings, readings, tags, stroke count, grade, JLPT level,
              frequency, and SKIP code. If a single kanji has no term result,
              YomiLens can fall back to the Kanji tab.
            </p>
            <p>
              Clicking a kanji inside a searched word is useful for checking the
              character without leaving the current popup flow.
            </p>
          </div>
          <figure>
            <img src="./screenshots/kanji-tab.png" alt="YomiLens Kanji tab" />
          </figure>
        </section>

        <section id="writer" className="section split reverse">
          <figure>
            <img
              src="./screenshots/japanese-table-rendering.png"
              alt="Japanese monolingual dictionary table rendering"
            />
            <figcaption>YomiLens renders richer Yomitan content, including tables and structured blocks.</figcaption>
          </figure>
          <div>
            <div className="section-head">
              <p className="section-kicker">05</p>
              <h2>Rich Entries And Writer Practice</h2>
            </div>
            <p>
              YomiLens supports richer dictionary entries, including examples,
              notes, tags, cross references, and tables. The optional Hanzi
              Writer tab adds stroke-order practice for Chinese characters.
            </p>
            <ul className="feature-list">
              {features.slice(4).map((feature) => (
                <li key={feature}>{feature}</li>
              ))}
            </ul>
          </div>
        </section>

        <section id="web" className="section">
          <div className="section-head">
            <p className="section-kicker">06</p>
            <h2>Web Lookup Buttons</h2>
          </div>
          <div className="panel">
            <p>
              Audio, YouGlish, and Google Images buttons are optional. In
              Settings → Web Lookup, choose which buttons appear and map each
              dictionary source to the right YouGlish or Google audio language.
            </p>
            <div className="mini-grid">
              <span>Audio can auto-speak or wait for click.</span>
              <span>YouGlish opens pronunciation examples inside Anki.</span>
              <span>IMG opens image search in an in-Anki popup.</span>
            </div>
          </div>
        </section>

        <section id="dictionaries" className="section">
          <div className="section-head">
            <p className="section-kicker">07</p>
            <h2>Dictionary Management</h2>
          </div>
          <div className="grid two">
            <div>
              <p>
                Use Settings → Dictionaries to download bundled dictionary ZIPs
                or import your own Yomitan/Yomichan-compatible ZIP files.
                YomiLens stores dictionary data in your Anki profile so updates
                do not wipe installed dictionaries.
              </p>
              <table>
                <tbody>
                  <tr>
                    <th>Download</th>
                    <td>Install curated dictionaries from the YomiLens dictionary repo.</td>
                  </tr>
                  <tr>
                    <th>Import ZIP</th>
                    <td>Load any compatible Yomitan/Yomichan dictionary package.</td>
                  </tr>
                  <tr>
                    <th>Manage</th>
                    <td>Enable, disable, reorder, delete, or re-download dictionaries.</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <figure>
              <img
                src="./screenshots/settings-dictionaries.png"
                alt="YomiLens dictionary downloader"
              />
            </figure>
          </div>
        </section>

        <section id="feature-guides" className="section feature-guides">
          <h2>Feature Guides</h2>
          <p>Pick a feature for its setup steps. Frequency, pitch accent and Custom CSS require a build that includes those features; they may not yet be available in your AnkiWeb release.</p>
          <div className="guide-links">
            {guides.map(({ id, title }) => <a key={id} href={`#${id}`}>{title}</a>)}
          </div>
          {guides.map(({ id, title, steps }) => (
            <article className="feature-guide" id={id} key={id}>
              <h3>{title}</h3>
              <ol>{steps.map(step => <li key={step}>{step}</li>)}</ol>
              {(id === "frequency" || id === "pitch-accent") && <p><a href="https://github.com/MarvNC/yomitan-dictionaries">Find Yomitan dictionary sources</a>. Check each source&apos;s license before downloading or redistributing.</p>}
              {id === "custom-css" && <pre><code>{`/* Enlarge definition text */\n.reading-definitions .g {\n  font-size: 18px;\n  line-height: 1.6;\n}`}</code></pre>}
            </article>
          ))}
        </section>

        <section id="troubleshooting" className="section">
          <div className="section-head">
            <p className="section-kicker">08</p>
            <h2>Troubleshooting</h2>
          </div>
          <div className="cards">
            {troubleshoot.map((item) => (
              <article key={item.title} className="card">
                <h3>{item.title}</h3>
                <p>{item.text}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="section credits">
          <h2>Credits</h2>
          <p>
            YomiLens is inspired by the Yomitan/Yomichan ecosystem and supports
            its dictionary format. Dictionary data credits include EDRDG,
            Jitendex, CC-CEDICT, LingLook / Phong Phan, Open English WordNet,
            Free Vietnamese Dictionary Project, LisaanMasry, and other open
            dictionary contributors.
          </p>
        </section>
      </div>
    </main>
  );
}
