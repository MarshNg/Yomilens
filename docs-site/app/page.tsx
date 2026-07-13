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
      <aside className="toc" aria-label="Table of contents">
        <a className="brand" href="#top">
          <span className="brand-mark">読</span>
          <span>
            <strong>YomiLens</strong>
            <small>Popup Dictionary Docs</small>
          </span>
        </a>
        <nav>
          {chapters.map(([id, label], index) => (
            <a key={id} href={`#${id}`}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              {label}
            </a>
          ))}
        </nav>
      </aside>

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
