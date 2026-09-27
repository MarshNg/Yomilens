# YomiLens Popup Dictionary

A **Yomitan/Yomichan-style popup dictionary for Anki**.

YomiLens brings fast, in-card dictionary lookup to Anki review. Select a word and open a clean popup directly on the card, with support for Yomitan/Yomichan dictionaries, multilingual lookup, inflected forms, kanji information, web lookup tools, nested popups, and optional writing practice.

![YomiLens popup dictionary demo](https://raw.githubusercontent.com/MarshNg/Yomilens/main/assets/ankiweb/yomilens-demo.gif)

## Highlights

- Look up words without leaving Anki review
- Import Yomitan/Yomichan-compatible dictionary ZIPs
- Download optional dictionaries from the built-in dictionary manager
- Support for English, Japanese, Chinese, Korean, Vietnamese, French, Arabic, and many more languages
- Resolve inflected word forms across supported languages
- Display rich dictionary content, including labels, examples, tables, images, and structured entries
- Open KANJIDIC-style character information in the Kanji tab
- Practice character stroke order with the optional Hanzi Writer tab
- Open nested lookups from words inside an existing definition
- Navigate lookup history with Back and Forward
- Add or edit personal dictionary entries
- Work locally inside Anki without a browser extension

## Web Lookup

Enable the optional web lookup buttons to hear a word with Google audio, find real pronunciation examples on YouGlish, or search Google Images. Languages and audio voices can be configured per dictionary source under **Tools -> YomiLens Settings -> Web Lookup**.

![YomiLens Web Lookup](https://raw.githubusercontent.com/MarshNg/Yomilens/main/assets/ankiweb/web-lookup.png)

## Themes and Dark Mode

Choose from multiple popup themes, including light and dark designs. Themes keep dictionary entries readable while letting YomiLens match the look of your Anki setup.

<p>
  <img src="https://raw.githubusercontent.com/MarshNg/Yomilens/main/assets/ankiweb/theme-deep-sea.png" alt="Deep Sea theme" width="360">
  <img src="https://raw.githubusercontent.com/MarshNg/Yomilens/main/assets/ankiweb/theme-aka-slate.png" alt="Aka Slate theme" width="360">
</p>

Configure the popup theme under **Tools -> YomiLens Settings -> General**.

## Nested Popups

Look up a word inside the current definition without losing your original result. Choose whether an internal lookup reuses the current popup or opens a nested popup beside it.

![YomiLens nested popup](https://raw.githubusercontent.com/MarshNg/Yomilens/main/assets/ankiweb/nested-popup.png)

Configure this under **Tools -> YomiLens Settings -> General -> Popup lookup behavior**.

## Flexible Popup Triggers

Open YomiLens by selecting text normally, or require a modifier key such as Shift, Ctrl, Alt/Option, or Command. Modifier-key mode is useful when card templates already use text selection for other interactions.

Configure the trigger under **Tools -> YomiLens Settings -> General -> Open popup trigger**.

## Easy Setup

1. Install the add-on and restart Anki.
2. Open **Tools -> YomiLens Settings**.
3. Go to **Dictionaries** and download a dictionary or import a Yomitan/Yomichan ZIP.
4. Go to **General** and enable the languages you want to look up.
5. Optionally configure themes, popup behavior, Web Lookup, and Hanzi Writer.
6. During review, select a word using your configured trigger.

After installing, importing, enabling, disabling, or deleting dictionaries, restart Anki before continuing lookup.

## Dictionary Sources

YomiLens can import Yomitan/Yomichan dictionary ZIPs. Optional downloadable dictionaries are maintained separately here:

[YomiLens Dictionaries](https://github.com/MarshNg/yomilens-dictionaries)

## Support and Documentation

- [YomiLens documentation](https://marshng.github.io/Yomilens/)
- [YomiLens on GitHub](https://github.com/MarshNg/Yomilens)
- [Support development on Ko-fi](https://ko-fi.com/marshnguyen)

## Credits

Special thanks to the [Yomitan project and contributors](https://github.com/yomidevs/yomitan) for the dictionary format, language tooling, and inspiration.

Dictionary data credits include EDRDG, Jitendex, CC-CEDICT, LingLook / Phong Phan, Open English WordNet, Free Vietnamese Dictionary Project, and other open dictionary contributors. Individual dictionary licenses and credits are shown inside YomiLens Settings.
