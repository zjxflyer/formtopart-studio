# FormToPart Studio verification

For 0.8.29, the release passed 21 native self-checks and 39 startup, navigation, and package checks. Tests used the packaged WebView2 window in an isolated Windows profile. On first launch and relaunch, Studio stayed on the home screen with the sample listed. The project card, **Open project**, and the project chooser each opened Step 1 on page 1 of the original PDF. All three previews matched the expected renders. **Continue to Step 2** opened the reviewed drawings. The gear opened **Assistant settings**, and its credential state matched before and after the test.

## 0.8.28 source replacement

The GitHub edition bundles `Original-customer-design_A200+A202.pdf` as the source for the West 15th Avenue sample. The embedded PDF is byte-for-byte identical to the supplied redacted PDF. Its SHA-256 is `9b00f28046b1a34695b11c4c14f9ac38291ddf9b11a7b8f119180c0ebb389102`.

The three pages render as the A101 floor plans, A200 kitchen, and A202 powder room. The sample retains its source document ID, and all 1,061 drawing and model evidence references resolve to that document and its corresponding source pages. The separately bundled 2D and 3D reference assets are unchanged.

The release was built outside the staging folder on Windows with Python 3.13.1 x64, Node.js 24.22.1, and pnpm 11.25.0. The Python dependency check and frontend type check passed. The Studio UI, portable 3D viewer, and Windows host compiled successfully. The cached WebView2 SDK matched the pinned checksum.

The [release EXE](SHA256SUMS.txt) passed 21 native self-checks, 64 service and archive checks, and 29 browser checks. A fresh profile and a profile created by the previous release displayed all three PDF previews. Every preview matched an independent render pixel for pixel, including after relaunch. Both profiles had 10 reviewed 2D drawings, 121 rendered model parts, and a working Excel download with seven rows covering 12 panels.

The upgrade preserved the saved name, revision history, model, and cutting list. It also preserved a separate project in the same test profile. Two source-level regression tests covered the upgrade, import of an older `.vwc`, and preservation of saved evidence that refers to a region in the prior illustration. The EXE contained all 17 expected sample assets, with no obsolete sample PDF or embedded API credentials detected. Tests used isolated profiles and made no paid API calls.
