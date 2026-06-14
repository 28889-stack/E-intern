<div align="center">
  <h1>📄 LiteDoc</h1>
  <p><b>A 100% Local, Browser-Based PDF to Markdown Converter.</b></p>
  
  [![Try it Live](https://img.shields.io/badge/🚀_Try_LiteDoc_Live-litedoc.xyz-6366f1?style=for-the-badge)](https://litedoc.xyz/)
  [![GitHub stars](https://img.shields.io/github/stars/0xovo/LiteDoc?style=for-the-badge&color=eab308)](https://github.com/0xovo/LiteDoc/stargazers)
  [![Twitter Follow](https://img.shields.io/badge/Follow_@0xovoo-000000?style=for-the-badge&logo=x&logoColor=white)](https://x.com/0xovoo)

  <br />
  
  <i>LiteDoc is a zero-setup, client-side tool built to extract text, images, tables, and math from PDFs. Save your LLM tokens and avoid wrestling with heavy backend environments—just drop your file in the browser and get clean Markdown.</i>
</div>

---

## 📸 See it in Action

**Full Main UI with Files Loaded**
<p align="center">
  <img alt="Full Main UI" src="https://github.com/user-attachments/assets/e47528eb-63cc-4af1-9baf-253e8c5ce4f0" width="100%" />
</p>

<table>
  <tr>
    <td width="50%" valign="top">
      <b>📝 Editor View</b><br>
      <img alt="Editor View" src="https://github.com/user-attachments/assets/e3406f44-05d3-49ee-9b51-7ff547596ea1" width="100%" />
    </td>
    <td width="50%" valign="top">
      <b>📂 Explorer View</b><br>
      <img alt="Explorer View" src="https://github.com/user-attachments/assets/860b196d-36b6-4462-90fa-dc8bd46ed811" width="100%" />
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <b>⏳ Loading Process</b><br>
      <img alt="Loading Process" src="https://github.com/user-attachments/assets/246b4a2d-0786-4996-a076-9d9f6fd8dee0" width="100%" />
    </td>
    <td width="50%" valign="top" align="center">
      <b>⚙️ Settings</b><br>
      <img alt="Settings View" src="https://github.com/user-attachments/assets/88ac3a21-0620-4ebc-a3c3-ebd2eca8ce72" />
    </td>
  </tr>
</table>

---

## 🥊 Why LiteDoc? (vs. Markitdown, Docling, Marker)

There are incredible, industry-standard tools out there for PDF parsing, like **Markitdown** (Microsoft), **Docling** (IBM), and **Marker**. However, they are fundamentally built for automated backend pipelines, which introduces significant friction for average users.

| Feature | 🐍 Markitdown / Docling / Marker | 🌐 LiteDoc |
| :--- | :--- | :--- |
| **Setup Required** | `pip install`, Python environments, Docker | **Zero.** Just open a web page. |
| **Target Audience** | Backend Devs, Data Engineers, AI Pipelines | **Everyone.** Students, researchers, writers. |
| **Processing** | Local CLI or Server-side API | **100% Client-side** (WASM + JS). |
| **Privacy** | Depends on your infrastructure setup | **Absolute.** Files never leave your device. |

**LiteDoc is for people who just want their Markdown *right now*.** 
No dependencies, no server uploads, no privacy concerns. It runs entirely on your local machine using your browser's resources.

---

## ✨ Key Features

- **🔒 100% Local & Private:** Core extraction, OCR, and bundling run entirely on your local CPU/GPU inside the browser. Files never touch any server.
- **🧩 Document Layout Analysis (DLA):** Employs a recursive **XY-Cut algorithm** to map out and isolate sidebars, headers, and multi-column flows, preventing horizontal text mixing.
- **🖼️ Smart OCR & OSD Router:** Runs a lightweight 400x400px pre-pass to auto-detect script direction and language, dynamically initializing WebAssembly Tesseract.js workers.
- **📊 Table & Vector Figures:** Detects vector lines to construct pristine GitHub-Flavored Markdown tables (supporting complex merged cells) and crops diagrams/charts as JPEG assets.
- **🧮 LaTeX Math Equations:** Automatically detects math formula bounding boxes and renders them with KaTeX.
- **🌍 Arabic & RTL Formatting:** Native support for Right-to-Left scripts with automatic line alignment and typography routing.
- **🛡️ Local Decryption:** Handles password-protected PDFs securely by prompt-unlocking them locally in the browser sandbox.
- **🧹 Custom Font Fallbacks:** Intercepts corrupted, custom-encoded "garbage" fonts, offering image-fallback options to ensure the document remains readable.
- **⚡ Batch Queuing & Memory Protection:** Processes large files in 10-page chunks and releases web canvas assets dynamically to prevent Out-Of-Memory (OOM) browser crashes.
- **📱 Fully Mobile Responsive:** Overhauled layout designed to offer full-editor features, document navigation, and settings toggles on mobile screens.
- **⏸️ Queue & Formatting Control:** Pause or skip processing tasks on demand, or use the "Unformat" action to strip markdown styling instantly.

## 🚀 Getting Started

Because LiteDoc is a purely client-side web application, you don't need to install any dependencies to run it! 

**The Easiest Way:**
1. Go to the [Releases page](https://github.com/0xovo/LiteDoc/releases).
2. Download the `index.html` file from the latest release.
3. Open the downloaded `index.html` file in any modern web browser (Chrome, Edge, Firefox, Safari) and drag and drop your PDFs!

**Run from Source:**
1. Clone or download this repository.
2. Open `dist/index.html` in your browser.

### Development & Custom Builds
If you want to modify the source code:
1. Make changes inside the `src/` directory (includes modular CSS and JS).
2. Bundle your changes into a single self-contained file by running:
   ```bash
   python scripts/build.py
   ```
3. The compiled production bundle will be updated at `dist/index.html`.

### Extracting Files
Once processing finishes, you can preview the generated Markdown directly in the built-in Ace Editor. 
Click **Download Files (.zip)** to get a neatly packaged archive containing your `.md` file and an attached folder containing all extracted images, tables, and charts.

## 🛠️ Architecture & Under the Hood

LiteDoc relies on a powerful stack of client-side libraries:
* **PDF.js** - Core parsing, rendering, and text-layer extraction.
* **Tesseract.js** - WebAssembly-based OCR for scanned document fallback.
* **JSZip** - Local, client-side ZIP packaging of extracted assets.
* **KaTeX** - Fast math typesetting in the Markdown previewer.
* **Ace Editor** - High-performance code editor for tweaking Markdown before export.

## 🧠 The Mathematics of Document Layout Analysis (DLA)

Unlike basic wrapper libraries that blindly extract text sequentially from top to bottom, LiteDoc utilizes advanced Document Layout Analysis (DLA) and topological graph algorithms natively in your browser. This ensures structurally perfect extractions for complex formats like multi-column scientific papers, journals, and math-heavy PDFs.

### 1. Recursive X-Y Cut Algorithm
I employ a top-down **Recursive XY-Cut Algorithm** to cleanly divide pages into discrete rectangular regions. 
- The algorithm projects text block coordinates onto the X and Y axes, building density histograms.
- It mathematically detects "valleys" (gutters or whitespace gaps) and slices the document recursively until it isolates individual columns, headers, and floating sidebars without cross-contamination.

### 2. Topological Sorting (Kahn's Algorithm)
After slicing the page, the geometric blocks are mapped into a Directed Acyclic Graph (DAG).
- I use **Kahn's Topological Sort** to determine the exact human reading order. 
- Edges in the graph are defined by strict geometric constraints (e.g., prioritizing $x_{min}$ alignment and strict horizontal overlap margins). This eliminates "column interleaving" bugs where a right column might be accidentally read before the left.

### 3. Mathematical Equation Heuristics & PUA Extraction
Mathematical formulas are notoriously difficult to extract because PDF engines often map math symbols to the Private Use Area (PUA) of Unicode.
- LiteDoc analyzes character densities and font registries (e.g., `CMSY`, `MathJax`) line-by-line. 
- When an equation block is detected ($Density_{math} > 25\%$), instead of outputting corrupted text, LiteDoc geometrically calculates the strict bounding box of the multi-line formula.
- The region is rendered onto an offscreen web canvas and seamlessly cropped into a high-fidelity image (`[IMAGE_MATH]`), perfectly preserving visual fractions and complex integrals.

### 4. Smart Gibberish Scorer
LiteDoc implements a robust Gibberish Scorer to identify heavily corrupted, custom-encoded "subset" fonts. It calculates a statistical $Suspicion Ratio$ based on illegal character blocks. When standard text fails this heuristic, LiteDoc safely isolates the text or dynamically routes the page to my WebAssembly OCR fallback (Tesseract.js) to recover the lost data.

## 🤝 Contributing & Future Updates

Contributions, issues, and feature requests are highly welcome! Since the goal is to keep the tool accessible and server-free, any PRs should adhere to the "100% client-side" philosophy.

**A Note on Future Updates:** Up until now, bugs and algorithmic edge-cases have been tracked manually by the maintainer. Because I currently don't have anyone actively opening issues on the repository, **future updates will be rolling out at a slower pace**. If you find a bug or want a feature, *please open an issue!* It is the best way to drive the next wave of development.

## 💬 Connect & Socials

- 🌐 **Website:** [litedoc.xyz](https://litedoc.xyz/)
- 🐙 **GitHub Repo:** [0xovo/LiteDoc](https://github.com/0xovo/LiteDoc)
- 🐦 **Twitter / X:** [@0xovoo](https://x.com/0xovoo)

## ☕ Support & Donations

LiteDoc is—and always will be—100% free and open-source. I originally built this tool to help broke students stop burning their paid AI tokens just to parse their study materials. 

If LiteDoc has saved you time, protected your privacy, or spared your wallet from expensive backend API costs, **please consider making a donation!** Your support is what keeps this project alive and continuously improving.

<a href="https://ko-fi.com/0xovo" target="_blank"><img src="https://storage.ko-fi.com/cdn/kofi1.png?v=3" alt="Buy Me A Coffee" height="36"></a>

---

*Built with ❤️ by 0xovo*
